from datetime import date, time

from fastapi.testclient import TestClient

from app.core.database import Base, engine
from app.main import app
from app.models import Department, RegistrationSession


def test_published_schedule_bookings_and_lifecycle_rules():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)

    from app.core.database import SessionLocal

    with SessionLocal() as db:
        department = Department(code="PUB", name="Published clinic", available_staff=3, default_service_minutes=12)
        db.add(department)
        db.flush()
        session = RegistrationSession(
            department_id=department.id,
            session_name="Published clinic registration",
            status="PUBLISHED",
            session_date=date.today(),
            total_capacity=10,
            initial_online_capacity=4,
            initial_physical_capacity=6,
            session_start_local=time(9, 0),
            session_end_local=time(12, 0),
            online_open_local=time(0, 0),
            online_close_local=time(23, 59),
            physical_open_local=time(0, 0),
            physical_close_local=time(23, 59),
        )
        db.add(session)
        db.commit()
        session_id = session.id

    with TestClient(app) as client:
        first = client.post(
            "/api/registration/sessions/{session_id}/online-bookings".replace("{session_id}", session_id),
            json={"patient_name": "First booking", "idempotency_key": "pub-1"},
        )
        assert first.status_code == 200

        second = client.post(
            "/api/registration/sessions/{session_id}/online-bookings".replace("{session_id}", session_id),
            json={"patient_name": "Second booking", "idempotency_key": "pub-2"},
        )
        assert second.status_code == 200

        duplicate = client.post(
            "/api/registration/sessions/{session_id}/online-bookings".replace("{session_id}", session_id),
            json={"patient_name": "Duplicate", "idempotency_key": "pub-2"},
        )
        assert duplicate.status_code == 200
        assert duplicate.json()["booking_reference"] == second.json()["booking_reference"]

        with SessionLocal() as db:
            session = db.get(RegistrationSession, session_id)
            session.reallocation_status = "completed"
            session.final_online_capacity = 2
            session.final_physical_capacity = 8
            db.commit()

        physical = client.post(
            "/api/registration/sessions/{session_id}/walk-ins".replace("{session_id}", session_id),
            json={"patient_name": "Walk-in patient", "idempotency_key": "walkin-1"},
        )
        assert physical.status_code == 200

        with SessionLocal() as db:
            session = db.get(RegistrationSession, session_id)
            assert session.status == "PUBLISHED"
            assert session.final_physical_capacity == 8
