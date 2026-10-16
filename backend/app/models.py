from datetime import date, datetime, time, timezone
from uuid import uuid4

from sqlalchemy import Boolean, Date, DateTime, Float, ForeignKey, Index, Integer, String, Text, Time, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(120))
    role: Mapped[str] = mapped_column(String(30), default="receptionist")
    department_id: Mapped[str | None] = mapped_column(ForeignKey("departments.id"), nullable=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Department(Base):
    __tablename__ = "departments"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    code: Mapped[str] = mapped_column(String(10), unique=True)
    name: Mapped[str] = mapped_column(String(120), unique=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    available_staff: Mapped[int] = mapped_column(Integer, default=2)
    default_service_minutes: Mapped[float] = mapped_column(Float, default=15)


class RegistrationSession(Base):
    __tablename__ = "registration_sessions"
    __table_args__ = (
        UniqueConstraint("department_id", "session_date", name="uq_registration_department_session_date"),
        Index("ix_registration_session_status", "reallocation_status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    department_id: Mapped[str | None] = mapped_column(ForeignKey("departments.id"), index=True, nullable=True)
    session_name: Mapped[str] = mapped_column(String(120), default="Morning Registration")
    status: Mapped[str] = mapped_column(String(20), default="DRAFT", index=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    session_date: Mapped[date] = mapped_column(Date, index=True, nullable=False)
    timezone_name: Mapped[str] = mapped_column(String(64), default="Asia/Kolkata")
    total_capacity: Mapped[int] = mapped_column(Integer, default=30)
    initial_online_capacity: Mapped[int] = mapped_column(Integer, default=12)
    initial_physical_capacity: Mapped[int] = mapped_column(Integer, default=18)
    auto_reallocate_online: Mapped[bool] = mapped_column(Boolean, default=True)
    session_start_local: Mapped[time] = mapped_column(Time, default=lambda: time(9, 0))
    session_end_local: Mapped[time] = mapped_column(Time, default=lambda: time(12, 0))
    online_open_local: Mapped[time] = mapped_column(Time, default=lambda: time(9, 0))
    online_close_local: Mapped[time] = mapped_column(Time, default=lambda: time(10, 0))
    physical_open_local: Mapped[time] = mapped_column(Time, default=lambda: time(10, 0))
    physical_close_local: Mapped[time] = mapped_column(Time, default=lambda: time(12, 0))
    reallocation_status: Mapped[str] = mapped_column(String(20), default="pending")
    reallocation_reason: Mapped[str | None] = mapped_column(String(200), nullable=True)
    reallocation_executed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    final_online_capacity: Mapped[int | None] = mapped_column(Integer, nullable=True)
    final_physical_capacity: Mapped[int | None] = mapped_column(Integer, nullable=True)
    confirmed_online_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class RegistrationBooking(Base):
    __tablename__ = "registration_bookings"
    __table_args__ = (
        UniqueConstraint("session_id", "idempotency_key", name="uq_registration_session_idempotency"),
        Index("ix_booking_session_channel", "session_id", "channel"),
        Index("ix_booking_status", "status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    session_id: Mapped[str] = mapped_column(ForeignKey("registration_sessions.id"), index=True)
    booking_reference: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    channel: Mapped[str] = mapped_column(String(20), default="online")
    status: Mapped[str] = mapped_column(String(20), default="confirmed", index=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(120), nullable=True)
    display_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    confirmed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancellation_reason: Mapped[str | None] = mapped_column(String(200), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class CapacityReallocationAudit(Base):
    __tablename__ = "capacity_reallocation_audits"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    session_id: Mapped[str] = mapped_column(ForeignKey("registration_sessions.id"), unique=True, index=True)
    previous_online_capacity: Mapped[int] = mapped_column(Integer)
    previous_physical_capacity: Mapped[int] = mapped_column(Integer)
    confirmed_online_count: Mapped[int] = mapped_column(Integer)
    released_online_slots: Mapped[int] = mapped_column(Integer)
    final_online_capacity: Mapped[int] = mapped_column(Integer)
    final_physical_capacity: Mapped[int] = mapped_column(Integer)
    executed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    executed_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    execution_reason: Mapped[str] = mapped_column(String(200))
    execution_status: Mapped[str] = mapped_column(String(20), default="completed")
    error_details: Mapped[str | None] = mapped_column(Text, nullable=True)


class Patient(Base):
    __tablename__ = "patients"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    reference: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    display_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class QueueTicket(Base):
    __tablename__ = "queue_tickets"
    __table_args__ = (
        UniqueConstraint("department_id", "token_day", "token_number", name="uq_department_daily_token"),
        Index("ix_ticket_department_status", "department_id", "status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    patient_id: Mapped[str] = mapped_column(ForeignKey("patients.id"), index=True)
    department_id: Mapped[str] = mapped_column(ForeignKey("departments.id"), index=True)
    token_day: Mapped[str] = mapped_column(String(10))
    token_number: Mapped[int] = mapped_column(Integer)
    appointment_type: Mapped[str] = mapped_column(String(20), default="walk-in")
    is_appointment: Mapped[bool] = mapped_column(Boolean, default=False)
    priority: Mapped[str] = mapped_column(String(20), default="routine")
    status: Mapped[str] = mapped_column(String(20), default="waiting", index=True)
    arrival_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    service_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    service_completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expected_service_minutes: Mapped[float] = mapped_column(Float)


class QueueEvent(Base):
    __tablename__ = "queue_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    ticket_id: Mapped[str] = mapped_column(ForeignKey("queue_tickets.id"), index=True)
    user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    from_status: Mapped[str | None] = mapped_column(String(20), nullable=True)
    to_status: Mapped[str] = mapped_column(String(20))
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class PredictionRecord(Base):
    __tablename__ = "prediction_records"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    ticket_id: Mapped[str] = mapped_column(ForeignKey("queue_tickets.id"), index=True)
    predicted_minutes: Mapped[float | None] = mapped_column(Float, nullable=True)
    model: Mapped[str] = mapped_column(String(60))
    input_snapshot: Mapped[str] = mapped_column(Text)
    predicted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    actual_wait_minutes: Mapped[float | None] = mapped_column(Float, nullable=True)


class SimulationRecord(Base):
    __tablename__ = "simulation_records"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    seed: Mapped[int] = mapped_column(Integer)
    parameters: Mapped[str] = mapped_column(Text)
    results: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    action: Mapped[str] = mapped_column(String(100))
    resource_type: Mapped[str] = mapped_column(String(50))
    resource_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
