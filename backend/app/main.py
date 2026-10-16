import json
import secrets
from contextlib import asynccontextmanager
from datetime import date, datetime, time, timezone
from zoneinfo import ZoneInfo

from fastapi import Depends, FastAPI, HTTPException, Query, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import Base, SessionLocal, engine, get_db, migrate_sqlite_schema
from app.core.security import create_access_token, hash_password, token_subject, verify_password
from app.models import (
    AuditLog,
    CapacityReallocationAudit,
    Department,
    Patient,
    PredictionRecord,
    QueueEvent,
    QueueTicket,
    RegistrationBooking,
    RegistrationSession,
    SimulationRecord,
    User,
)
from app.services.prediction import predict_wait
from app.services.simulation import compare_scenarios


@asynccontextmanager
async def lifespan(_: FastAPI):
    initialize_database()
    yield


app = FastAPI(
    title="FlowCare API",
    version="1.0.0",
    description="Hospital waiting-time intelligence (synthetic-data-first).",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
bearer = HTTPBearer(auto_error=False)
TRANSITIONS = {
    "waiting": {"in_service", "cancelled", "no_show"},
    "in_service": {"completed"},
    "registered": {"waiting", "cancelled"},
}
STAFF_ROLES = {"admin", "receptionist", "staff"}
ADMIN_ROLES = {"admin"}

def utc_datetime(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def elapsed_minutes(later: datetime, earlier: datetime) -> float:
    return max(0.0, (utc_datetime(later) - utc_datetime(earlier)).total_seconds() / 60)


DEFAULT_REGISTRATION_SESSION = {
    "session_name": "Morning Registration",
    "total_capacity": 30,
    "initial_online_capacity": 12,
    "initial_physical_capacity": 18,
    "session_start_local": time(9, 0),
    "session_end_local": time(12, 0),
    "online_open_local": time(9, 0),
    "online_close_local": time(10, 0),
    "physical_open_local": time(10, 0),
    "physical_close_local": time(12, 0),
    "timezone_name": "Asia/Kolkata",
}


def validate_registration_session_payload(payload: dict) -> dict:
    total_capacity = int(payload.get("total_capacity", 0))
    initial_online = int(payload.get("initial_online_capacity", 0))
    initial_physical = int(payload.get("initial_physical_capacity", 0))
    if total_capacity <= 0 or initial_online < 0 or initial_physical < 0:
        raise ValueError("Registration capacities must be positive integers with non-negative allocations.")
    if initial_online + initial_physical != total_capacity:
        raise ValueError("The online and physical allocations must sum to the total session capacity.")
    if payload.get("session_start_local") and payload.get("session_end_local"):
        start = payload["session_start_local"]; end = payload["session_end_local"]
        if start >= end:
            raise ValueError("Session end time must be later than the start time.")
    if payload.get("online_open_local") and payload.get("online_close_local"):
        online_open = payload["online_open_local"]; online_close = payload["online_close_local"]
        if online_open >= online_close:
            raise ValueError("Online booking window must be valid and end after it opens.")
    if payload.get("physical_open_local") and payload.get("physical_close_local"):
        physical_open = payload["physical_open_local"]; physical_close = payload["physical_close_local"]
        if physical_open >= physical_close:
            raise ValueError("Physical registration window must be valid and end after it opens.")
    return {
        "total_capacity": total_capacity,
        "initial_online_capacity": initial_online,
        "initial_physical_capacity": initial_physical,
    }


def registration_status_for(session: RegistrationSession, now: datetime, channel: str) -> str:
    time_value = now.astimezone(ZoneInfo(session.timezone_name)).time()
    open_time = session.online_open_local if channel == "online" else session.physical_open_local
    close_time = session.online_close_local if channel == "online" else session.physical_close_local
    if time_value < open_time:
        return "NOT_OPEN"
    if time_value >= close_time:
        return "CLOSED"
    return "OPEN"


def confirmed_booking_count(db: Session, session_id: str, channel: str | None = None) -> int:
    query = select(func.count(RegistrationBooking.id)).where(
        RegistrationBooking.session_id == session_id,
        RegistrationBooking.status == "confirmed",
    )
    if channel is not None:
        query = query.where(RegistrationBooking.channel == channel)
    return int(db.scalar(query) or 0)


def reconcile_registration_session(
    db: Session,
    session: RegistrationSession,
    *,
    executed_by: User | None = None,
    reason: str = "scheduled_cutoff",
) -> RegistrationSession:
    if session.reallocation_status == "completed":
        return session
    confirmed_online_count = confirmed_booking_count(db, session.id, "online")
    if not session.auto_reallocate_online:
        final_online_capacity = session.initial_online_capacity
        final_physical_capacity = session.initial_physical_capacity
        released_online_slots = 0
    else:
        released_online_slots = max(session.initial_online_capacity - confirmed_online_count, 0)
        final_online_capacity = confirmed_online_count
        final_physical_capacity = session.initial_physical_capacity + released_online_slots
        if final_online_capacity + final_physical_capacity != session.total_capacity:
            raise ValueError("Reallocation would exceed the configured session capacity.")
    session.final_online_capacity = final_online_capacity
    session.final_physical_capacity = final_physical_capacity
    session.confirmed_online_count = confirmed_online_count
    session.reallocation_status = "completed"
    session.reallocation_reason = reason
    session.reallocation_executed_at = datetime.now(timezone.utc)
    audit_row = db.scalar(
        select(CapacityReallocationAudit).where(CapacityReallocationAudit.session_id == session.id)
    )
    if audit_row is None:
        audit_row = CapacityReallocationAudit(
            session_id=session.id,
            previous_online_capacity=session.initial_online_capacity,
            previous_physical_capacity=session.initial_physical_capacity,
            confirmed_online_count=confirmed_online_count,
            released_online_slots=released_online_slots,
            final_online_capacity=final_online_capacity,
            final_physical_capacity=final_physical_capacity,
            executed_by=executed_by.id if executed_by else None,
            execution_reason=reason,
            execution_status="completed",
        )
        db.add(audit_row)
    else:
        audit_row.previous_online_capacity = session.initial_online_capacity
        audit_row.previous_physical_capacity = session.initial_physical_capacity
        audit_row.confirmed_online_count = confirmed_online_count
        audit_row.released_online_slots = released_online_slots
        audit_row.final_online_capacity = final_online_capacity
        audit_row.final_physical_capacity = final_physical_capacity
        audit_row.executed_at = datetime.now(timezone.utc)
        audit_row.executed_by = executed_by.id if executed_by else audit_row.executed_by
        audit_row.execution_reason = reason
        audit_row.execution_status = "completed"
        audit_row.error_details = None
    db.flush()
    return session


def ensure_registration_session(db: Session, session_date: date | None = None) -> RegistrationSession:
    target_date = session_date or date.today()
    session = db.scalar(select(RegistrationSession).where(RegistrationSession.session_date == target_date))
    if session is not None:
        return session
    config = dict(DEFAULT_REGISTRATION_SESSION)
    session = RegistrationSession(session_date=target_date, **config)
    db.add(session)
    db.flush()
    return session


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=200)


class SignupRequest(BaseModel):
    email: EmailStr
    display_name: str = Field(min_length=1, max_length=120)
    password: str = Field(min_length=6, max_length=200)


class BootstrapAdminRequest(BaseModel):
    email: EmailStr
    display_name: str = Field(min_length=1, max_length=120)
    password: str = Field(min_length=12, max_length=200)


class PatientCreate(BaseModel):
    department_id: str
    appointment_type: str = Field(default="walk-in", pattern="^(walk-in|appointment)$")
    display_name: str | None = Field(default=None, max_length=120)
    priority: str = Field(default="routine", pattern="^(routine|priority)$")
    expected_service_minutes: float | None = Field(default=None, gt=0, le=240)


class TicketStatusUpdate(BaseModel):
    status: str = Field(pattern="^(waiting|in_service|completed|cancelled|no_show)$")


class StaffUpdate(BaseModel):
    available_staff: int = Field(ge=0, le=100)


class DepartmentCreate(BaseModel):
    code: str = Field(min_length=2, max_length=10, pattern="^[A-Z0-9]+$")
    name: str = Field(min_length=2, max_length=120)
    is_active: bool = True
    description: str | None = Field(default=None, max_length=500)
    available_staff: int = Field(default=2, ge=0, le=100)
    default_service_minutes: float = Field(default=15, gt=0, le=240)


class RegistrationSessionCreate(BaseModel):
    department_id: str | None = None
    session_name: str = Field(default="Morning Registration", min_length=2, max_length=120)
    status: str = Field(default="DRAFT", pattern="^(DRAFT|PUBLISHED|CANCELLED|COMPLETED)$")
    description: str | None = Field(default=None, max_length=1000)
    session_date: date = Field(default_factory=date.today)
    total_capacity: int = Field(default=30, ge=1)
    initial_online_capacity: int = Field(default=12, ge=0)
    initial_physical_capacity: int = Field(default=18, ge=0)
    auto_reallocate_online: bool = True
    session_start_local: time = Field(default=time(9, 0))
    session_end_local: time = Field(default=time(12, 0))
    online_open_local: time = Field(default=time(9, 0))
    online_close_local: time = Field(default=time(10, 0))
    physical_open_local: time = Field(default=time(10, 0))
    physical_close_local: time = Field(default=time(12, 0))
    timezone_name: str = Field(default="Asia/Kolkata", min_length=2, max_length=64)


class RegistrationSessionUpdate(BaseModel):
    department_id: str | None = None
    session_name: str | None = Field(default=None, min_length=2, max_length=120)
    status: str | None = Field(default=None, pattern="^(DRAFT|PUBLISHED|CANCELLED|COMPLETED)$")
    description: str | None = Field(default=None, max_length=1000)
    total_capacity: int | None = Field(default=None, ge=1)
    initial_online_capacity: int | None = Field(default=None, ge=0)
    initial_physical_capacity: int | None = Field(default=None, ge=0)
    auto_reallocate_online: bool | None = None
    session_start_local: time | None = None
    session_end_local: time | None = None
    online_open_local: time | None = None
    online_close_local: time | None = None
    physical_open_local: time | None = None
    physical_close_local: time | None = None
    timezone_name: str | None = Field(default=None, min_length=2, max_length=64)


class RegistrationBookingRequest(BaseModel):
    patient_name: str | None = Field(default=None, max_length=120)
    idempotency_key: str | None = Field(default=None, min_length=1, max_length=120)


class SimulationRequest(BaseModel):
    patients: int = Field(default=120, ge=1, le=5000)
    arrival_rate_per_hour: float = Field(default=12, gt=0, le=300)
    service_mean_minutes: float = Field(default=15, gt=0, le=240)
    baseline_doctors: int = Field(default=2, ge=0, le=100)
    alternative_doctors: int = Field(default=3, ge=0, le=100)
    seed: int = Field(default=42, ge=0, le=2_147_483_647)


class UserCreate(BaseModel):
    email: EmailStr
    display_name: str = Field(min_length=1, max_length=120)
    password: str = Field(min_length=12, max_length=200)
    role: str = Field(pattern="^(admin|receptionist|staff)$")


class PublicPatientStatus(BaseModel):
    token: str
    department: str
    status: str
    estimated_wait_minutes: float | None


def current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    db: Session = Depends(get_db),
) -> User:
    subject = token_subject(credentials.credentials) if credentials else None
    user = db.get(User, subject) if subject else None
    if user is None or not user.active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Valid login required.")
    return user


def optional_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    db: Session = Depends(get_db),
) -> User | None:
    if credentials is None:
        return None
    subject = token_subject(credentials.credentials)
    user = db.get(User, subject) if subject else None
    return user if user and user.active else None


def require_roles(*roles: str):
    def dependency(user: User = Depends(current_user)) -> User:
        if user.role not in roles:
            raise HTTPException(status_code=403, detail="Your account cannot perform this action.")
        return user
    return dependency


def audit(db: Session, user: User | None, action: str, resource_type: str, resource_id: str | None = None):
    db.add(AuditLog(user_id=user.id if user else None, action=action, resource_type=resource_type, resource_id=resource_id))


def create_user_account(
    db: Session,
    *,
    email: str,
    display_name: str,
    password: str,
    role: str,
    actor: User | None = None,
    action: str = "staff.created",
) -> User:
    normalized_email = email.strip().lower()
    if db.scalar(select(User).where(User.email == normalized_email)):
        raise HTTPException(status_code=409, detail="An account with this email already exists.")
    member = User(
        email=normalized_email,
        display_name=display_name.strip(),
        role=role,
        password_hash=hash_password(password),
    )
    db.add(member)
    db.flush()
    audit(db, actor, action, "user", member.id)
    db.commit()
    return member


def ticket_response(db: Session, ticket: QueueTicket) -> dict:
    patient = db.get(Patient, ticket.patient_id)
    department = db.get(Department, ticket.department_id)
    waiting_ahead = db.scalar(
        select(func.count(QueueTicket.id)).where(
            QueueTicket.department_id == ticket.department_id,
            QueueTicket.status.in_(("waiting", "in_service")),
            QueueTicket.arrival_at < ticket.arrival_at,
        )
    ) or 0
    return {
        "id": ticket.id,
        "patient_reference": patient.reference,
        "display_name": patient.display_name,
        "department_id": department.id,
        "department": department.name,
        "token": f"{department.code}-{ticket.token_number:03d}",
        "token_number": ticket.token_number,
        "appointment_type": ticket.appointment_type,
        "priority": ticket.priority,
        "status": ticket.status,
        "arrival_at": utc_datetime(ticket.arrival_at).isoformat(),
        "service_started_at": utc_datetime(ticket.service_started_at).isoformat() if ticket.service_started_at else None,
        "service_completed_at": utc_datetime(ticket.service_completed_at).isoformat() if ticket.service_completed_at else None,
        "patients_ahead": waiting_ahead,
        "actual_wait_minutes": round(elapsed_minutes(ticket.service_started_at, ticket.arrival_at), 1)
        if ticket.service_started_at else None,
    }


def initialize_database():
    if len(settings.jwt_secret) < 32:
        raise RuntimeError("Set JWT_SECRET to a random value of at least 32 characters before starting FlowCare.")
    if settings.flowcare_demo_password and len(settings.flowcare_demo_password) < 12:
        raise RuntimeError("FLOWCARE_DEMO_PASSWORD must contain at least 12 characters.")
    Base.metadata.create_all(bind=engine)
    migrate_sqlite_schema(engine)
    with SessionLocal() as db:
        defaults = [
            ("GEN", "General Medicine", 3, 15.0),
            ("CAR", "Cardiology", 2, 20.0),
            ("ORT", "Orthopedics", 2, 18.0),
        ]
        for code, name, staff, minutes in defaults:
            if not db.scalar(select(Department).where(Department.code == code)):
                db.add(Department(code=code, name=name, available_staff=staff, default_service_minutes=minutes))
        seed_dates = [date.today(), date.today().fromordinal(date.today().toordinal() + 1)]
        for seed_day in seed_dates:
            ensure_registration_session(db, seed_day)
        if settings.flowcare_demo_password:
            existing = db.scalar(select(User).where(User.email == "admin@flowcare.local"))
            if not existing:
                db.add(User(
                    email="admin@flowcare.local",
                    display_name="FlowCare Administrator",
                    role="admin",
                    password_hash=hash_password(settings.flowcare_demo_password),
                ))
        db.commit()


def registration_session_payload(session: RegistrationSession, *, db: Session | None = None) -> dict:
    now = datetime.now(ZoneInfo(session.timezone_name))
    online_count = confirmed_booking_count(db, session.id, "online") if db is not None else 0
    physical_count = confirmed_booking_count(db, session.id, "physical") if db is not None else 0
    remaining_capacity = max(session.total_capacity - online_count - physical_count, 0)
    department = None
    if session.department_id and db is not None:
        department = db.get(Department, session.department_id)
    return {
        "id": session.id,
        "department_id": session.department_id,
        "department_name": department.name if department else None,
        "department_code": department.code if department else None,
        "session_name": session.session_name,
        "status": session.status,
        "description": session.description,
        "session_date": session.session_date.isoformat(),
        "timezone_name": session.timezone_name,
        "total_capacity": session.total_capacity,
        "initial_online_capacity": session.initial_online_capacity,
        "initial_physical_capacity": session.initial_physical_capacity,
        "final_online_capacity": session.final_online_capacity if session.final_online_capacity is not None else session.initial_online_capacity,
        "final_physical_capacity": session.final_physical_capacity if session.final_physical_capacity is not None else session.initial_physical_capacity,
        "auto_reallocate_online": session.auto_reallocate_online,
        "session_start_local": session.session_start_local.isoformat(),
        "session_end_local": session.session_end_local.isoformat(),
        "online_open_local": session.online_open_local.isoformat(),
        "online_close_local": session.online_close_local.isoformat(),
        "physical_open_local": session.physical_open_local.isoformat(),
        "physical_close_local": session.physical_close_local.isoformat(),
        "online_status": registration_status_for(session, now, "online"),
        "physical_status": registration_status_for(session, now, "physical"),
        "reallocation_status": session.reallocation_status,
        "reallocation_executed_at": session.reallocation_executed_at.isoformat() if session.reallocation_executed_at else None,
        "confirmed_online_bookings": online_count,
        "confirmed_physical_bookings": physical_count,
        "remaining_capacity": remaining_capacity,
        "created_at": session.created_at.isoformat(),
        "updated_at": session.updated_at.isoformat(),
    }


def registration_booking_payload(booking: RegistrationBooking, *, session: RegistrationSession | None = None) -> dict:
    effective_session = session or booking.session_id
    return {
        "id": booking.id,
        "booking_reference": booking.booking_reference,
        "session_id": booking.session_id,
        "channel": booking.channel,
        "status": booking.status,
        "patient_name": booking.display_name,
        "created_at": booking.created_at.isoformat(),
        "confirmed_at": booking.confirmed_at.isoformat(),
        "cancelled_at": booking.cancelled_at.isoformat() if booking.cancelled_at else None,
        "cancellation_reason": booking.cancellation_reason,
        "idempotency_key": booking.idempotency_key,
    }


@app.get("/health")
def health():
    return {"status": "ok", "service": "FlowCare API"}


@app.post("/api/auth/login")
def login(payload: LoginRequest, db: Session = Depends(get_db)):
    user = db.scalar(select(User).where(User.email == payload.email.lower()))
    if not user or not user.active or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Incorrect email or password.")
    return {
        "access_token": create_access_token(user.id),
        "token_type": "bearer",
        "user": {"id": user.id, "email": user.email, "display_name": user.display_name, "role": user.role},
    }


@app.post("/api/auth/signup", status_code=201)
@app.post("/api/auth/register", status_code=201)
def signup(payload: SignupRequest, db: Session = Depends(get_db)):
    user = create_user_account(
        db,
        email=payload.email,
        display_name=payload.display_name,
        password=payload.password,
        role="receptionist",
        actor=None,
        action="auth.signup",
    )
    return {
        "access_token": create_access_token(user.id),
        "token_type": "bearer",
        "user": {"id": user.id, "email": user.email, "display_name": user.display_name, "role": user.role},
    }


@app.post("/api/admin/bootstrap", status_code=201)
@app.post("/api/admin/setup", status_code=201)
def bootstrap_admin_account(payload: BootstrapAdminRequest, db: Session = Depends(get_db)):
    if db.scalar(select(User).where(User.role == "admin")):
        raise HTTPException(status_code=409, detail="An administrator account already exists.")
    if settings.flowcare_demo_password:
        raise HTTPException(status_code=403, detail="Administrator bootstrap is managed by the deployment configuration.")
    user = create_user_account(
        db,
        email=payload.email,
        display_name=payload.display_name,
        password=payload.password,
        role="admin",
        actor=None,
        action="auth.bootstrap_admin",
    )
    return {
        "access_token": create_access_token(user.id),
        "token_type": "bearer",
        "user": {"id": user.id, "email": user.email, "display_name": user.display_name, "role": user.role},
    }


@app.get("/api/auth/me")
def me(user: User = Depends(current_user)):
    return {"id": user.id, "email": user.email, "display_name": user.display_name, "role": user.role}


@app.get("/api/departments")
def departments(_: User = Depends(require_roles(*STAFF_ROLES)), db: Session = Depends(get_db)):
    return [
        {
            "id": item.id,
            "code": item.code,
            "name": item.name,
            "is_active": item.is_active,
            "description": item.description,
            "available_staff": item.available_staff,
            "default_service_minutes": item.default_service_minutes,
        }
        for item in db.scalars(select(Department).order_by(Department.name))
    ]


@app.post("/api/departments", status_code=201)
def create_department(
    payload: DepartmentCreate, user: User = Depends(require_roles(*ADMIN_ROLES)), db: Session = Depends(get_db)
):
    if db.scalar(select(Department).where((Department.code == payload.code) | (Department.name == payload.name))):
        raise HTTPException(status_code=409, detail="A department with this code or name already exists.")
    department = Department(**payload.model_dump())
    db.add(department)
    db.flush()
    audit(db, user, "department.created", "department", department.id)
    db.commit()
    return {"id": department.id, **payload.model_dump()}


@app.patch("/api/departments/{department_id}")
def update_department(
    department_id: str,
    payload: DepartmentCreate,
    user: User = Depends(require_roles(*ADMIN_ROLES)),
    db: Session = Depends(get_db),
):
    department = db.get(Department, department_id)
    if not department:
        raise HTTPException(status_code=404, detail="Department not found.")
    if payload.code.lower() != department.code.lower() or payload.name.lower() != department.name.lower():
        existing = db.scalar(select(Department).where((Department.code == payload.code) | (Department.name == payload.name)))
        if existing and existing.id != department.id:
            raise HTTPException(status_code=409, detail="A department with this code or name already exists.")
    for field, value in payload.model_dump().items():
        setattr(department, field, value)
    audit(db, user, "department.updated", "department", department.id)
    db.commit()
    return {
        "id": department.id,
        "code": department.code,
        "name": department.name,
        "is_active": department.is_active,
        "description": department.description,
        "available_staff": department.available_staff,
        "default_service_minutes": department.default_service_minutes,
    }


@app.get("/api/registration/sessions")
def list_registration_sessions(_: User | None = Depends(optional_current_user), db: Session = Depends(get_db)):
    sessions = db.scalars(select(RegistrationSession).order_by(RegistrationSession.session_date)).all()
    return [registration_session_payload(session, db=db) for session in sessions]


@app.get("/api/registration/sessions/{session_id}")
def get_registration_session(session_id: str, _: User | None = Depends(optional_current_user), db: Session = Depends(get_db)):
    session = db.get(RegistrationSession, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Registration session not found.")
    return registration_session_payload(session, db=db)


@app.get("/api/registration/sessions/{session_id}/capacity")
def get_registration_session_capacity(session_id: str, _: User | None = Depends(optional_current_user), db: Session = Depends(get_db)):
    session = db.get(RegistrationSession, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Registration session not found.")
    now = datetime.now(ZoneInfo(session.timezone_name))
    confirmed_online = confirmed_booking_count(db, session.id, "online")
    confirmed_physical = confirmed_booking_count(db, session.id, "physical")
    total_used = confirmed_online + confirmed_physical
    final_online = session.final_online_capacity if session.final_online_capacity is not None else session.initial_online_capacity
    final_physical = session.final_physical_capacity if session.final_physical_capacity is not None else session.initial_physical_capacity
    return {
        "session_id": session.id,
        "session_date": session.session_date.isoformat(),
        "total_capacity": session.total_capacity,
        "initial_online_capacity": session.initial_online_capacity,
        "initial_physical_capacity": session.initial_physical_capacity,
        "final_online_capacity": final_online,
        "final_physical_capacity": final_physical,
        "confirmed_online_bookings": confirmed_online,
        "confirmed_physical_bookings": confirmed_physical,
        "total_registrations": total_used,
        "remaining_capacity": max(session.total_capacity - total_used, 0),
        "online_status": registration_status_for(session, now, "online"),
        "physical_status": registration_status_for(session, now, "physical"),
        "reallocation_status": session.reallocation_status,
    }


@app.post("/api/registration/sessions/{session_id}/online-bookings")
@app.post("/api/registration/sessions/{session_id}/online_bookings")
def create_online_booking(
    session_id: str,
    payload: RegistrationBookingRequest,
    db: Session = Depends(get_db),
):
    session = db.get(RegistrationSession, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Registration session not found.")
    now = datetime.now(ZoneInfo(session.timezone_name))
    if session.status in {"CANCELLED", "COMPLETED"}:
        raise HTTPException(status_code=409, detail="This registration session is no longer accepting bookings.")
    if session.status == "PUBLISHED":
        if session.online_open_local > now.time() or now.time() >= session.online_close_local:
            raise HTTPException(status_code=409, detail="Online registration is not currently open for this session.")
    online_capacity_limit = session.final_online_capacity if session.final_online_capacity is not None else session.initial_online_capacity
    if session.status == "PUBLISHED":
        online_count = confirmed_booking_count(db, session.id, "online")
        if online_count >= online_capacity_limit:
            raise HTTPException(status_code=409, detail="Online places for this session are full. Physical registration opens at 10:00 AM, subject to available capacity.")
    if payload.idempotency_key:
        existing = db.scalar(
            select(RegistrationBooking).where(
                RegistrationBooking.session_id == session.id,
                RegistrationBooking.idempotency_key == payload.idempotency_key,
            )
        )
        if existing is not None:
            return registration_booking_payload(existing, session=session)
    if confirmed_booking_count(db, session.id) >= session.total_capacity:
        raise HTTPException(status_code=409, detail="This session has reached its registration capacity.")
    booking = RegistrationBooking(
        session_id=session.id,
        booking_reference=f"REG-{secrets.token_hex(6).upper()}",
        channel="online",
        status="confirmed",
        idempotency_key=payload.idempotency_key,
        display_name=payload.patient_name,
    )
    db.add(booking)
    db.flush()
    audit(db, None, "registration.online_booked", "registration_booking", booking.id)
    db.commit()
    return registration_booking_payload(booking, session=session)


@app.get("/api/registration/bookings/{booking_reference}")
def get_registration_booking(booking_reference: str, db: Session = Depends(get_db)):
    booking = db.scalar(select(RegistrationBooking).where(RegistrationBooking.booking_reference == booking_reference))
    if not booking:
        raise HTTPException(status_code=404, detail="Booking reference not found.")
    session = db.get(RegistrationSession, booking.session_id)
    return registration_booking_payload(booking, session=session)


@app.post("/api/registration/bookings/{booking_reference}/cancel")
def cancel_registration_booking(booking_reference: str, db: Session = Depends(get_db)):
    booking = db.scalar(select(RegistrationBooking).where(RegistrationBooking.booking_reference == booking_reference))
    if not booking:
        raise HTTPException(status_code=404, detail="Booking reference not found.")
    if booking.status == "cancelled":
        return registration_booking_payload(booking)
    booking.status = "cancelled"
    booking.cancelled_at = datetime.now(timezone.utc)
    booking.cancellation_reason = "Customer cancellation"
    db.add(booking)
    db.flush()
    db.commit()
    return registration_booking_payload(booking)


@app.post("/api/registration/sessions/{session_id}/walk-ins")
@app.post("/api/registration/sessions/{session_id}/walk_ins")
def create_walk_in_registration(
    session_id: str,
    payload: RegistrationBookingRequest,
    db: Session = Depends(get_db),
):
    session = db.get(RegistrationSession, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Registration session not found.")
    now = datetime.now(ZoneInfo(session.timezone_name))
    if session.status in {"CANCELLED", "COMPLETED"}:
        raise HTTPException(status_code=409, detail="This registration session is no longer accepting bookings.")
    if session.status == "PUBLISHED":
        if session.reallocation_status == "pending" and now.time() >= session.online_close_local:
            reconcile_registration_session(db, session, reason="lazy_cutoff_reconciliation")
        if now.time() < session.physical_open_local or now.time() >= session.physical_close_local:
            raise HTTPException(status_code=409, detail="Physical registration opens at 10:00 AM and closes at 12:00 PM for this session.")
        if session.reallocation_status != "completed":
            raise HTTPException(status_code=409, detail="The session cutoff has not yet been finalized.")
    final_capacity = session.final_physical_capacity if session.final_physical_capacity is not None else session.initial_physical_capacity
    if confirmed_booking_count(db, session.id, "physical") >= final_capacity:
        raise HTTPException(status_code=409, detail="Physical registration capacity is exhausted for this session.")
    if confirmed_booking_count(db, session.id) >= session.total_capacity:
        raise HTTPException(status_code=409, detail="This session has reached its registration capacity.")
    if payload.idempotency_key:
        existing = db.scalar(
            select(RegistrationBooking).where(
                RegistrationBooking.session_id == session.id,
                RegistrationBooking.idempotency_key == payload.idempotency_key,
            )
        )
        if existing is not None:
            return registration_booking_payload(existing, session=session)
    booking = RegistrationBooking(
        session_id=session.id,
        booking_reference=f"REG-{secrets.token_hex(6).upper()}",
        channel="physical",
        status="confirmed",
        idempotency_key=payload.idempotency_key,
        display_name=payload.patient_name,
    )
    db.add(booking)
    db.flush()
    audit(db, None, "registration.walk_in", "registration_booking", booking.id)
    db.commit()
    return registration_booking_payload(booking, session=session)


@app.get("/api/registration/sessions/{session_id}/reallocation")
def get_registration_reallocation(session_id: str, _: User | None = Depends(optional_current_user), db: Session = Depends(get_db)):
    session = db.get(RegistrationSession, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Registration session not found.")
    audit_row = db.scalar(select(CapacityReallocationAudit).where(CapacityReallocationAudit.session_id == session.id))
    if audit_row is None:
        return {
            "session_id": session.id,
            "status": session.reallocation_status,
            "released_online_slots": 0,
            "final_online_capacity": session.final_online_capacity if session.final_online_capacity is not None else session.initial_online_capacity,
            "final_physical_capacity": session.final_physical_capacity if session.final_physical_capacity is not None else session.initial_physical_capacity,
            "executed_at": None,
        }
    return {
        "session_id": session.id,
        "status": audit_row.execution_status,
        "released_online_slots": audit_row.released_online_slots,
        "final_online_capacity": audit_row.final_online_capacity,
        "final_physical_capacity": audit_row.final_physical_capacity,
        "executed_at": audit_row.executed_at.isoformat(),
        "reason": audit_row.execution_reason,
    }


@app.post("/api/admin/registration/sessions", status_code=201)
def create_registration_session(
    payload: RegistrationSessionCreate,
    user: User = Depends(require_roles(*ADMIN_ROLES)),
    db: Session = Depends(get_db),
):
    data = payload.model_dump()
    try:
        validated = validate_registration_session_payload(data)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if payload.department_id:
        department = db.get(Department, payload.department_id)
        if not department:
            raise HTTPException(status_code=404, detail="Department not found.")
    if payload.department_id:
        existing = db.scalar(
            select(RegistrationSession).where(
                RegistrationSession.department_id == payload.department_id,
                RegistrationSession.session_date == payload.session_date,
            )
        )
        if existing:
            raise HTTPException(status_code=409, detail="A schedule is already configured for that department and date.")
    if payload.status == "PUBLISHED" and payload.department_id is None:
        raise HTTPException(status_code=422, detail="A published schedule must be assigned to a department.")
    session = RegistrationSession(
        department_id=payload.department_id,
        session_name=payload.session_name,
        status=payload.status,
        description=payload.description,
        session_date=payload.session_date,
        timezone_name=payload.timezone_name,
        total_capacity=validated["total_capacity"],
        initial_online_capacity=validated["initial_online_capacity"],
        initial_physical_capacity=validated["initial_physical_capacity"],
        auto_reallocate_online=payload.auto_reallocate_online,
        session_start_local=payload.session_start_local,
        session_end_local=payload.session_end_local,
        online_open_local=payload.online_open_local,
        online_close_local=payload.online_close_local,
        physical_open_local=payload.physical_open_local,
        physical_close_local=payload.physical_close_local,
    )
    db.add(session)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        if payload.department_id and db.scalar(
            select(RegistrationSession).where(
                RegistrationSession.department_id == payload.department_id,
                RegistrationSession.session_date == payload.session_date,
            )
        ):
            raise HTTPException(
                status_code=409,
                detail="A schedule is already configured for that department and date.",
            ) from exc
        raise
    audit(db, user, "registration.session_created", "registration_session", session.id)
    db.commit()
    return registration_session_payload(session, db=db)


@app.patch("/api/admin/registration/sessions/{session_id}")
def update_registration_session(
    session_id: str,
    payload: RegistrationSessionUpdate,
    user: User = Depends(require_roles(*ADMIN_ROLES)),
    db: Session = Depends(get_db),
):
    session = db.get(RegistrationSession, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Registration session not found.")
    update_values = payload.model_dump(exclude_unset=True)
    if not update_values:
        return registration_session_payload(session, db=db)
    new_total = update_values.get("total_capacity", session.total_capacity)
    new_online = update_values.get("initial_online_capacity", session.initial_online_capacity)
    new_physical = update_values.get("initial_physical_capacity", session.initial_physical_capacity)
    if new_online + new_physical != new_total:
        raise HTTPException(status_code=422, detail="The online and physical allocations must sum to the total session capacity.")
    active_usage = confirmed_booking_count(db, session.id, "online") + confirmed_booking_count(db, session.id, "physical")
    if new_total < active_usage:
        raise HTTPException(status_code=409, detail="The session capacity cannot be lowered below confirmed registrations without an approved adjustment workflow.")
    if update_values.get("status") == "PUBLISHED" and session.department_id is None:
        raise HTTPException(status_code=422, detail="A published schedule must be assigned to a department.")
    for field, value in update_values.items():
        if value is not None:
            setattr(session, field, value)
    if session.reallocation_status == "completed":
        session.final_online_capacity = None
        session.final_physical_capacity = None
        session.reallocation_status = "pending"
    db.flush()
    audit(db, user, "registration.session_updated", "registration_session", session.id)
    db.commit()
    return registration_session_payload(session, db=db)


@app.post("/api/admin/registration/sessions/{session_id}/reallocate")
def reallocate_registration_session(
    session_id: str,
    user: User = Depends(require_roles(*ADMIN_ROLES)),
    db: Session = Depends(get_db),
):
    session = db.get(RegistrationSession, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Registration session not found.")
    try:
        reconcile_registration_session(db, session, executed_by=user, reason="admin_reconciliation")
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    audit(db, user, "registration.reallocated", "registration_session", session.id)
    db.commit()
    return get_registration_reallocation(session_id, None, db)


@app.get("/api/admin/registration/sessions/{session_id}/audit")
def get_registration_session_audit(session_id: str, _: User = Depends(require_roles(*ADMIN_ROLES)), db: Session = Depends(get_db)):
    session = db.get(RegistrationSession, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Registration session not found.")
    audit_row = db.scalar(select(CapacityReallocationAudit).where(CapacityReallocationAudit.session_id == session.id))
    if audit_row is None:
        return {"session_id": session.id, "audit_events": []}
    return {
        "session_id": session.id,
        "audit_events": [{
            "id": audit_row.id,
            "session_id": audit_row.session_id,
            "previous_online_capacity": audit_row.previous_online_capacity,
            "previous_physical_capacity": audit_row.previous_physical_capacity,
            "confirmed_online_count": audit_row.confirmed_online_count,
            "released_online_slots": audit_row.released_online_slots,
            "final_online_capacity": audit_row.final_online_capacity,
            "final_physical_capacity": audit_row.final_physical_capacity,
            "executed_at": audit_row.executed_at.isoformat(),
            "executed_by": audit_row.executed_by,
            "execution_reason": audit_row.execution_reason,
            "execution_status": audit_row.execution_status,
            "error_details": audit_row.error_details,
        }],
    }


@app.get("/api/staff")
def staff_list(_: User = Depends(require_roles(*ADMIN_ROLES)), db: Session = Depends(get_db)):
    return [
        {"id": item.id, "email": item.email, "display_name": item.display_name, "role": item.role, "active": item.active}
        for item in db.scalars(select(User).order_by(User.display_name))
    ]


@app.post("/api/admin/users", status_code=201)
@app.post("/api/staff", status_code=201)
def create_staff(
    payload: UserCreate, user: User = Depends(require_roles(*ADMIN_ROLES)), db: Session = Depends(get_db)
):
    member = create_user_account(
        db,
        email=payload.email,
        display_name=payload.display_name,
        password=payload.password,
        role=payload.role,
        actor=user,
        action="staff.created",
    )
    return {"id": member.id, "email": member.email, "display_name": member.display_name, "role": member.role}


@app.patch("/api/staff/{department_id}/availability")
def update_availability(
    department_id: str,
    payload: StaffUpdate,
    user: User = Depends(require_roles(*ADMIN_ROLES)),
    db: Session = Depends(get_db),
):
    department = db.get(Department, department_id)
    if not department:
        raise HTTPException(status_code=404, detail="Department not found.")
    department.available_staff = payload.available_staff
    audit(db, user, "staff.availability_updated", "department", department.id)
    db.commit()
    return {"department_id": department.id, "available_staff": department.available_staff}


@app.post("/api/patients", status_code=201)
def register_patient(
    payload: PatientCreate,
    user: User = Depends(require_roles("admin", "receptionist")),
    db: Session = Depends(get_db),
):
    department = db.get(Department, payload.department_id)
    if not department:
        raise HTTPException(status_code=404, detail="Department not found.")
    today = date.today().isoformat()
    # Acquire a row write lock before reading the next daily sequence number.
    db.execute(
        update(Department)
        .where(Department.id == department.id)
        .values(available_staff=Department.available_staff)
    )
    last_number = db.scalar(
        select(func.max(QueueTicket.token_number)).where(
            QueueTicket.department_id == department.id, QueueTicket.token_day == today
        )
    ) or 0
    patient = Patient(reference=f"FC-{secrets.token_hex(16).upper()}", display_name=payload.display_name)
    db.add(patient)
    db.flush()
    ticket = QueueTicket(
        patient_id=patient.id,
        department_id=department.id,
        token_day=today,
        token_number=last_number + 1,
        appointment_type=payload.appointment_type,
        is_appointment=payload.appointment_type == "appointment",
        priority=payload.priority,
        expected_service_minutes=payload.expected_service_minutes or department.default_service_minutes,
    )
    db.add(ticket)
    db.flush()
    db.add(QueueEvent(ticket_id=ticket.id, user_id=user.id, from_status=None, to_status="waiting"))
    audit(db, user, "patient.registered", "queue_ticket", ticket.id)
    db.commit()
    return ticket_response(db, ticket)


@app.get("/api/queue/current")
def current_queue(
    department_id: str | None = None,
    ticket_status: str | None = Query(default=None, alias="status", pattern="^(waiting|in_service|completed|cancelled|no_show)$"),
    limit: int = Query(default=100, ge=1, le=250),
    _: User = Depends(require_roles(*STAFF_ROLES)),
    db: Session = Depends(get_db),
):
    query = select(QueueTicket).order_by(QueueTicket.arrival_at, QueueTicket.token_number).limit(limit)
    if department_id:
        query = query.where(QueueTicket.department_id == department_id)
    if ticket_status:
        query = query.where(QueueTicket.status == ticket_status)
    return [ticket_response(db, ticket) for ticket in db.scalars(query)]


@app.get("/api/queue/tickets/{ticket_id}")
def get_ticket(ticket_id: str, _: User = Depends(require_roles(*STAFF_ROLES)), db: Session = Depends(get_db)):
    ticket = db.get(QueueTicket, ticket_id)
    if not ticket:
        raise HTTPException(status_code=404, detail="Queue ticket not found.")
    return ticket_response(db, ticket)


@app.patch("/api/queue/tickets/{ticket_id}/status")
def update_ticket_status(
    ticket_id: str,
    payload: TicketStatusUpdate,
    user: User = Depends(require_roles(*STAFF_ROLES)),
    db: Session = Depends(get_db),
):
    ticket = db.get(QueueTicket, ticket_id)
    if not ticket:
        raise HTTPException(status_code=404, detail="Queue ticket not found.")
    if payload.status not in TRANSITIONS.get(ticket.status, set()):
        raise HTTPException(status_code=409, detail=f"Cannot change ticket status from {ticket.status} to {payload.status}.")
    previous = ticket.status
    now = datetime.now(timezone.utc)
    ticket.status = payload.status
    if payload.status == "in_service":
        ticket.service_started_at = now
    elif payload.status == "completed":
        ticket.service_completed_at = now
        db.query(PredictionRecord).filter(
            PredictionRecord.ticket_id == ticket.id, PredictionRecord.actual_wait_minutes.is_(None)
        ).update({
            PredictionRecord.actual_wait_minutes:
                elapsed_minutes(ticket.service_started_at, ticket.arrival_at)
                if ticket.service_started_at else 0.0
        })
    db.add(QueueEvent(ticket_id=ticket.id, user_id=user.id, from_status=previous, to_status=payload.status))
    audit(db, user, f"queue.{payload.status}", "queue_ticket", ticket.id)
    db.commit()
    return ticket_response(db, ticket)


@app.post("/api/predictions/wait-time")
def prediction(
    ticket_id: str,
    user: User = Depends(require_roles(*STAFF_ROLES)),
    db: Session = Depends(get_db),
):
    ticket = db.get(QueueTicket, ticket_id)
    if not ticket:
        raise HTTPException(status_code=404, detail="Queue ticket not found.")
    result = predict_wait(db, ticket)
    record = PredictionRecord(
        ticket_id=ticket.id,
        predicted_minutes=result["predicted_minutes"],
        model=result["model"],
        input_snapshot=json.dumps(result["inputs"]),
        predicted_at=datetime.now(timezone.utc),
    )
    db.add(record)
    db.flush()
    result["id"] = record.id
    audit(db, user, "prediction.created", "queue_ticket", ticket.id)
    db.commit()
    return result


@app.get("/api/predictions/evaluation")
def prediction_evaluation(_: User = Depends(require_roles(*STAFF_ROLES)), db: Session = Depends(get_db)):
    records = list(db.scalars(select(PredictionRecord).where(PredictionRecord.actual_wait_minutes.is_not(None))))
    if not records:
        return {"evaluated_predictions": 0, "mae_minutes": None, "note": "Complete tickets with saved predictions to measure error."}
    errors = [abs(record.predicted_minutes - record.actual_wait_minutes) for record in records]
    return {"evaluated_predictions": len(errors), "mae_minutes": round(sum(errors) / len(errors), 1)}


@app.get("/api/predictions/{prediction_id}")
def get_prediction(
    prediction_id: str, _: User = Depends(require_roles(*STAFF_ROLES)), db: Session = Depends(get_db)
):
    record = db.get(PredictionRecord, prediction_id)
    if not record:
        raise HTTPException(status_code=404, detail="Prediction not found.")
    return {
        "id": record.id,
        "ticket_id": record.ticket_id,
        "predicted_minutes": record.predicted_minutes,
        "model": record.model,
        "predicted_at": record.predicted_at.isoformat(),
        "actual_wait_minutes": record.actual_wait_minutes,
    }


@app.post("/api/simulations/compare", status_code=201)
def run_simulation(
    payload: SimulationRequest,
    user: User = Depends(require_roles(*ADMIN_ROLES)),
    db: Session = Depends(get_db),
):
    result = compare_scenarios(**payload.model_dump())
    record = SimulationRecord(seed=payload.seed, parameters=payload.model_dump_json(), results=json.dumps(result))
    db.add(record)
    db.flush()
    audit(db, user, "simulation.created", "simulation", record.id)
    db.commit()
    return {"id": record.id, **result}


@app.get("/api/simulations/{simulation_id}/results")
def simulation_results(
    simulation_id: str, _: User = Depends(require_roles(*STAFF_ROLES)), db: Session = Depends(get_db)
):
    record = db.get(SimulationRecord, simulation_id)
    if not record:
        raise HTTPException(status_code=404, detail="Simulation not found.")
    return {"id": record.id, **json.loads(record.results)}


@app.get("/api/analytics/overview")
def analytics(_: User = Depends(require_roles(*STAFF_ROLES)), db: Session = Depends(get_db)):
    total = db.scalar(select(func.count(QueueTicket.id))) or 0
    counts = {
        state: db.scalar(select(func.count(QueueTicket.id)).where(QueueTicket.status == state)) or 0
        for state in ("waiting", "in_service", "completed")
    }
    departments_result = []
    for department in db.scalars(select(Department).order_by(Department.name)):
        departments_result.append({
            "department_id": department.id,
            "department": department.name,
            "waiting": db.scalar(select(func.count(QueueTicket.id)).where(
                QueueTicket.department_id == department.id, QueueTicket.status == "waiting"
            )) or 0,
            "in_service": db.scalar(select(func.count(QueueTicket.id)).where(
                QueueTicket.department_id == department.id, QueueTicket.status == "in_service"
            )) or 0,
            "available_staff": department.available_staff,
        })
    completed = list(db.scalars(select(QueueTicket).where(
        QueueTicket.status == "completed", QueueTicket.service_started_at.is_not(None)
    )))
    actual_waits = [elapsed_minutes(ticket.service_started_at, ticket.arrival_at) for ticket in completed]
    evaluated = list(db.scalars(select(PredictionRecord).where(PredictionRecord.actual_wait_minutes.is_not(None))))
    errors = [
        abs(record.predicted_minutes - record.actual_wait_minutes)
        for record in evaluated
        if record.predicted_minutes is not None and record.actual_wait_minutes is not None
    ]
    return {
        "total_registered": total,
        **counts,
        "actual_average_wait_minutes": round(sum(actual_waits) / len(actual_waits), 1) if actual_waits else None,
        "prediction_evaluated_mae_minutes": round(sum(errors) / len(errors), 1) if errors else None,
        "departments": departments_result,
        "data_label": "Live database records; synthetic demo data unless authorized real data is entered.",
    }


@app.get("/api/analytics/departments")
def department_analytics(_: User = Depends(require_roles(*STAFF_ROLES)), db: Session = Depends(get_db)):
    return analytics(_, db)["departments"]


@app.get("/api/analytics/trends")
def analytics_trends(_: User = Depends(require_roles(*STAFF_ROLES)), db: Session = Depends(get_db)):
    tickets = list(db.scalars(select(QueueTicket).order_by(QueueTicket.arrival_at)))
    hourly: dict[str, int] = {}
    for ticket in tickets:
        key = utc_datetime(ticket.arrival_at).astimezone().strftime("%Y-%m-%d %H:00")
        hourly[key] = hourly.get(key, 0) + 1
    return [{"hour": hour, "registered": count} for hour, count in hourly.items()]


@app.get("/api/analytics/bottlenecks")
def bottlenecks(_: User = Depends(require_roles(*STAFF_ROLES)), db: Session = Depends(get_db)):
    alerts = []
    for department in db.scalars(select(Department)):
        waiting = db.scalar(select(func.count(QueueTicket.id)).where(
            QueueTicket.department_id == department.id, QueueTicket.status == "waiting"
        )) or 0
        active = db.scalar(select(func.count(QueueTicket.id)).where(
            QueueTicket.department_id == department.id, QueueTicket.status == "in_service"
        )) or 0
        threshold = max(8, department.available_staff * 4)
        if waiting >= threshold:
            alerts.append({
                "department": department.name,
                "severity": "high" if waiting >= threshold * 2 else "medium",
                "waiting": waiting,
                "message": f"{waiting} patients are waiting while {active} are in service. This is a queue-length signal, not proof of cause.",
            })
    return alerts


@app.get("/api/audit-logs")
def audit_logs(_: User = Depends(require_roles(*ADMIN_ROLES)), db: Session = Depends(get_db)):
    return [
        {"id": item.id, "user_id": item.user_id, "action": item.action, "resource_type": item.resource_type,
         "resource_id": item.resource_id, "occurred_at": item.occurred_at.isoformat()}
        for item in db.scalars(select(AuditLog).order_by(AuditLog.occurred_at.desc()).limit(100))
    ]


@app.get("/api/patient/tickets/{reference}", response_model=PublicPatientStatus)
def patient_status(reference: str, db: Session = Depends(get_db)):
    patient = db.scalar(select(Patient).where(Patient.reference == reference))
    if not patient:
        raise HTTPException(status_code=404, detail="Patient reference not found.")
    ticket = db.scalar(select(QueueTicket).where(QueueTicket.patient_id == patient.id).order_by(QueueTicket.arrival_at.desc()))
    if not ticket:
        raise HTTPException(status_code=404, detail="Queue ticket not found.")
    department = db.get(Department, ticket.department_id)
    estimate = predict_wait(db, ticket)["predicted_minutes"] if ticket.status in ("waiting", "in_service") else None
    return PublicPatientStatus(
        token=f"{department.code}-{ticket.token_number:03d}",
        department=department.name,
        status=ticket.status,
        estimated_wait_minutes=estimate,
    )
