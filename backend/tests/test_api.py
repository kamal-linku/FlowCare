from concurrent.futures import ThreadPoolExecutor

from fastapi.testclient import TestClient

from app.core.database import Base, engine
from app.core.security import hash_password
from app.main import app
from app.models import Department, User


def test_login_rbac_and_queue_flow():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    from app.core.database import SessionLocal

    with SessionLocal() as db:
        department = Department(code="TST", name="Test clinic", available_staff=1, default_service_minutes=12)
        admin = User(
            email="admin@example.com", display_name="Admin", role="admin",
            password_hash=hash_password("correct-horse-battery"),
        )
        db.add_all([department, admin])
        db.commit()
        department_id = department.id

    with TestClient(app) as client:
        assert client.get("/api/departments").status_code == 401
        response = client.post("/api/auth/login", json={"email": "admin@example.com", "password": "correct-horse-battery"})
        assert response.status_code == 200
        headers = {"Authorization": f"Bearer {response.json()['access_token']}"}
        registration = client.post(
            "/api/patients",
            json={"department_id": department_id, "appointment_type": "walk-in", "display_name": "Synthetic patient"},
            headers=headers,
        )
        assert registration.status_code == 201
        ticket = registration.json()
        assert ticket["token"] == "TST-001"
        assert client.get("/api/queue/current", headers=headers).json()[0]["id"] == ticket["id"]
        prediction = client.post(
            "/api/predictions/wait-time", params={"ticket_id": ticket["id"]}, headers=headers
        )
        assert prediction.status_code == 200
        assert prediction.json()["model"] == "historical-median-baseline"
        assert prediction.json()["inputs"]["available_staff"] == 1
        assert client.get(
            f"/api/predictions/{prediction.json()['id']}", headers=headers
        ).status_code == 200
        with SessionLocal() as db:
            db.get(Department, department_id).available_staff = 0
            db.commit()
        no_staff = client.post(
            "/api/predictions/wait-time", params={"ticket_id": ticket["id"]}, headers=headers
        )
        assert no_staff.json()["predicted_minutes"] is None
        with SessionLocal() as db:
            db.get(Department, department_id).available_staff = 1
            db.commit()
        started = client.patch(
            f"/api/queue/tickets/{ticket['id']}/status", json={"status": "in_service"}, headers=headers
        )
        assert started.status_code == 200
        assert client.patch(
            f"/api/queue/tickets/{ticket['id']}/status", json={"status": "waiting"}, headers=headers
        ).status_code == 409
        assert client.patch(
            f"/api/queue/tickets/{ticket['id']}/status", json={"status": "completed"}, headers=headers
        ).json()["service_started_at"] == started.json()["service_started_at"]
        assert client.get(f"/api/patient/tickets/{ticket['patient_reference']}").status_code == 200
        assert client.patch(
            f"/api/queue/tickets/{ticket['id']}/status", json={"status": "in_service"}, headers=headers
        ).status_code == 409


def test_simulation_endpoint_requires_admin():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    from app.core.database import SessionLocal

    with SessionLocal() as db:
        db.add(User(
            email="desk@example.com", display_name="Desk", role="receptionist",
            password_hash=hash_password("correct-horse-battery"),
        ))
        db.commit()
    with TestClient(app) as client:
        response = client.post("/api/auth/login", json={"email": "desk@example.com", "password": "correct-horse-battery"})
        headers = {"Authorization": f"Bearer {response.json()['access_token']}"}
        assert client.post(
            "/api/simulations/compare", json={"patients": 20}, headers=headers
        ).status_code == 403


def test_public_signup_creates_receptionist_and_returns_login_token():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)

    with TestClient(app) as client:
        response = client.post(
            "/api/auth/signup",
            json={
                "email": "new@example.com",
                "display_name": "New User",
                "password": "private-password",
                "role": "admin",
            },
        )

        assert response.status_code == 201
        assert response.json()["user"]["role"] == "receptionist"
        headers = {"Authorization": f"Bearer {response.json()['access_token']}"}
        current_user = client.get("/api/auth/me", headers=headers)
        assert current_user.status_code == 200
        assert current_user.json()["display_name"] == "New User"
        login = client.post(
            "/api/auth/login",
            json={"email": "new@example.com", "password": "private-password"},
        )
        assert login.status_code == 200
        assert login.json()["user"]["role"] == "receptionist"


def test_concurrent_registration_issues_unique_tokens():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    from app.core.database import SessionLocal

    with SessionLocal() as db:
        department = Department(code="CON", name="Concurrent clinic", available_staff=2, default_service_minutes=10)
        admin = User(
            email="parallel@example.com", display_name="Admin", role="admin",
            password_hash=hash_password("correct-horse-battery"),
        )
        db.add_all([department, admin])
        db.commit()
        department_id = department.id

    with TestClient(app) as client:
        login = client.post(
            "/api/auth/login", json={"email": "parallel@example.com", "password": "correct-horse-battery"}
        )
        headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
        payload = {"department_id": department_id, "appointment_type": "walk-in"}

        def create_ticket(_):
            return client.post("/api/patients", json=payload, headers=headers)

        with ThreadPoolExecutor(max_workers=4) as pool:
            responses = list(pool.map(create_ticket, range(8)))
        assert all(response.status_code == 201 for response in responses)
        numbers = sorted(response.json()["token_number"] for response in responses)
        assert numbers == list(range(1, 9))
