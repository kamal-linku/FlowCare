from datetime import date, time

from fastapi.testclient import TestClient

from app.core.database import Base, SessionLocal, engine
from app.main import app
from app.models import RegistrationSession


def test_registration_session_configuration_and_reallocation():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)

    with SessionLocal() as db:
        session = RegistrationSession(
            session_name="Morning Registration",
            session_date=date.today(),
            total_capacity=30,
            initial_online_capacity=12,
            initial_physical_capacity=18,
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
        response = client.get(f"/api/registration/sessions/{session_id}/capacity")
        assert response.status_code == 200
        assert response.json()["total_capacity"] == 30
        assert response.json()["remaining_capacity"] == 30

        online = client.post(
            f"/api/registration/sessions/{session_id}/online-bookings",
            json={"patient_name": "First patient", "idempotency_key": "booking-1"},
        )
        assert online.status_code == 200
        assert online.json()["channel"] == "online"

        second = client.post(
            f"/api/registration/sessions/{session_id}/online-bookings",
            json={"patient_name": "Second patient", "idempotency_key": "booking-2"},
        )
        assert second.status_code == 200
        assert second.json()["channel"] == "online"

        response = client.get(f"/api/registration/sessions/{session_id}/capacity")
        assert response.json()["confirmed_online_bookings"] == 2

        with SessionLocal() as db:
            session = db.get(RegistrationSession, session_id)
            session.reallocation_status = "completed"
            session.final_online_capacity = 2
            session.final_physical_capacity = 28
            db.commit()

        physical = client.post(
            f"/api/registration/sessions/{session_id}/walk-ins",
            json={"patient_name": "Walk-in patient", "idempotency_key": "walkin-1"},
        )
        assert physical.status_code == 200
        assert physical.json()["channel"] == "physical"

        capacity = client.get(f"/api/registration/sessions/{session_id}/capacity")
        assert capacity.status_code == 200
        assert capacity.json()["confirmed_physical_bookings"] == 1
