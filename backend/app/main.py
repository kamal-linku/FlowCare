import json
import secrets
from contextlib import asynccontextmanager
from datetime import date, datetime, timezone
from fastapi import Depends, FastAPI, HTTPException, Query, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import Base, SessionLocal, engine, get_db
from app.core.security import create_access_token, hash_password, token_subject, verify_password
from app.models import (
    AuditLog, Department, Patient, PredictionRecord, QueueEvent, QueueTicket, SimulationRecord, User,
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


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=200)


class SignupRequest(BaseModel):
    email: EmailStr
    display_name: str = Field(min_length=1, max_length=120)
    password: str = Field(min_length=6, max_length=200)


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
    available_staff: int = Field(default=2, ge=0, le=100)
    default_service_minutes: float = Field(default=15, gt=0, le=240)


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


def require_roles(*roles: str):
    def dependency(user: User = Depends(current_user)) -> User:
        if user.role not in roles:
            raise HTTPException(status_code=403, detail="Your account cannot perform this action.")
        return user
    return dependency


def audit(db: Session, user: User | None, action: str, resource_type: str, resource_id: str | None = None):
    db.add(AuditLog(user_id=user.id if user else None, action=action, resource_type=resource_type, resource_id=resource_id))


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
    with SessionLocal() as db:
        defaults = [
            ("GEN", "General Medicine", 3, 15.0),
            ("CAR", "Cardiology", 2, 20.0),
            ("ORT", "Orthopedics", 2, 18.0),
        ]
        for code, name, staff, minutes in defaults:
            if not db.scalar(select(Department).where(Department.code == code)):
                db.add(Department(code=code, name=name, available_staff=staff, default_service_minutes=minutes))
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
    email = payload.email.lower()
    if db.scalar(select(User).where(User.email == email)):
        raise HTTPException(status_code=409, detail="An account with this email already exists.")
    user = User(
        email=email,
        display_name=payload.display_name.strip(),
        role="receptionist",
        password_hash=hash_password(payload.password),
    )
    db.add(user)
    db.flush()
    audit(db, user, "auth.signup", "user", user.id)
    db.commit()
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
        {"id": item.id, "code": item.code, "name": item.name, "available_staff": item.available_staff,
         "default_service_minutes": item.default_service_minutes}
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


@app.get("/api/staff")
def staff_list(_: User = Depends(require_roles(*ADMIN_ROLES)), db: Session = Depends(get_db)):
    return [
        {"id": item.id, "email": item.email, "display_name": item.display_name, "role": item.role, "active": item.active}
        for item in db.scalars(select(User).order_by(User.display_name))
    ]


@app.post("/api/staff", status_code=201)
def create_staff(
    payload: UserCreate, user: User = Depends(require_roles(*ADMIN_ROLES)), db: Session = Depends(get_db)
):
    email = payload.email.lower()
    if db.scalar(select(User).where(User.email == email)):
        raise HTTPException(status_code=409, detail="An account with this email already exists.")
    member = User(
        email=email,
        display_name=payload.display_name,
        role=payload.role,
        password_hash=hash_password(payload.password),
    )
    db.add(member)
    db.flush()
    audit(db, user, "staff.created", "user", member.id)
    db.commit()
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
