from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path

import joblib
import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Department, QueueTicket

MODEL_PATH = Path(__file__).resolve().parents[3] / "ml" / "artifacts" / "wait_time_model.joblib"
ACTIVE = ("waiting", "in_service")


@lru_cache(maxsize=1)
def _load_model():
    return joblib.load(MODEL_PATH) if MODEL_PATH.exists() else None


def _minutes_between(later: datetime, earlier: datetime) -> float:
    if later.tzinfo is None:
        later = later.replace(tzinfo=timezone.utc)
    if earlier.tzinfo is None:
        earlier = earlier.replace(tzinfo=timezone.utc)
    return max(0.0, (later - earlier).total_seconds() / 60)


def predict_wait(db: Session, ticket: QueueTicket) -> dict:
    now = datetime.now().astimezone()
    department = db.get(Department, ticket.department_id)
    if department is None:
        raise ValueError("Ticket department no longer exists.")

    active = list(
        db.scalars(
            select(QueueTicket)
            .where(
                QueueTicket.department_id == ticket.department_id,
                QueueTicket.status.in_(ACTIVE),
                QueueTicket.arrival_at <= ticket.arrival_at,
            )
            .order_by(QueueTicket.arrival_at, QueueTicket.token_number)
        )
    )
    waiting_ahead = [item for item in active if item.status == "waiting" and item.id != ticket.id]
    completed_durations = [
        duration
        for item in db.scalars(
            select(QueueTicket)
            .where(
                QueueTicket.department_id == ticket.department_id,
                QueueTicket.status == "completed",
                QueueTicket.service_started_at.is_not(None),
                QueueTicket.service_completed_at.is_not(None),
            )
            .order_by(QueueTicket.service_completed_at.desc())
            .limit(100)
        )
        if (duration := _minutes_between(item.service_completed_at, item.service_started_at)) > 0
    ]
    typical = float(np.median(completed_durations[-100:])) if completed_durations else float(
        department.default_service_minutes
    )
    servers = max(0, department.available_staff)
    server_free_at = [0.0] * servers
    occupied = [item for item in active if item.status == "in_service" and item.id != ticket.id]
    for index, item in enumerate(occupied[:servers]):
        remaining = (
            max(0.0, item.expected_service_minutes - _minutes_between(now, item.service_started_at))
            if item.service_started_at
            else typical
        )
        server_free_at[index] = remaining

    features = np.array(
        [[len(waiting_ahead), servers, typical, len(occupied), now.hour, float(ticket.is_appointment)]],
        dtype=float,
    )
    model_used = "historical-median-baseline"
    estimate: float | None = None
    if servers == 0:
        influences = ["No staff currently available; a finite wait estimate is unavailable."]
    elif (model := _load_model()) is not None:
        estimate = max(0.0, float(model.predict(features)[0]))
        model_used = "trained-random-forest"
    elif server_free_at:
        for item in waiting_ahead:
            server_index = int(np.argmin(server_free_at))
            elapsed = (
                _minutes_between(now, item.service_started_at)
                if item.status == "in_service" and item.service_started_at
                else 0.0
            )
            duration = item.expected_service_minutes
            server_free_at[server_index] += max(0.0, duration - elapsed)
        estimate = min(server_free_at) if server_free_at else 0.0

    # The range is a transparent planning band (± one typical service); it is not
    # a statistically calibrated prediction interval.
    lower = max(0.0, estimate - typical) if estimate is not None else None
    upper = estimate + typical if estimate is not None else None
    if servers > 0:
        influences = [
            f"{len(waiting_ahead)} active patient(s) ahead",
            f"{servers} available staff member(s)",
            f"Typical service duration: {typical:.0f} minutes",
        ]
    return {
        "ticket_id": ticket.id,
        "predicted_minutes": round(estimate, 1) if estimate is not None else None,
        "lower_minutes": round(lower, 1) if lower is not None else None,
        "upper_minutes": round(upper, 1) if upper is not None else None,
        "model": model_used,
        "predicted_at": now.isoformat(),
        "inputs": {
            "patients_ahead": len(waiting_ahead),
            "available_staff": servers,
            "typical_service_minutes": round(typical, 2),
            "occupied_staff": len(occupied),
            "hour": now.hour,
            "is_appointment": ticket.is_appointment,
        },
        "uncertainty_note": (
            "No staff currently available; a finite wait estimate is unavailable."
            if estimate is None
            else "Planning range, not a calibrated confidence interval."
        ),
        "factors": influences,
    }
