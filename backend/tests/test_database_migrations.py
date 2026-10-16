from datetime import date

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import Session

from app.core.database import migrate_sqlite_schema
from app.models import RegistrationSession


def test_migrate_existing_sqlite_departments_table(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'legacy.db'}")
    try:
        with engine.begin() as connection:
            connection.exec_driver_sql(
                "CREATE TABLE departments ("
                "id VARCHAR(36) PRIMARY KEY, "
                "code VARCHAR(10) NOT NULL UNIQUE, "
                "name VARCHAR(120) NOT NULL UNIQUE)"
            )
            connection.execute(
                text("INSERT INTO departments (id, code, name) VALUES (:id, :code, :name)"),
                {"id": "department-1", "code": "GEN", "name": "General Medicine"},
            )

        migrate_sqlite_schema(engine)

        columns = {column["name"] for column in inspect(engine).get_columns("departments")}
        assert {"is_active", "description", "available_staff", "default_service_minutes"} <= columns
        with engine.connect() as connection:
            department = connection.execute(
                text(
                    "SELECT is_active, description, available_staff, default_service_minutes "
                    "FROM departments WHERE code = :code"
                ),
                {"code": "GEN"},
            ).one()
        assert department == (1, None, 2, 15.0)
    finally:
        engine.dispose()


def test_migrate_legacy_unique_registration_date_constraint(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'legacy-schedules.db'}")
    try:
        with engine.begin() as connection:
            connection.exec_driver_sql(
                "CREATE TABLE departments ("
                "id VARCHAR(36) PRIMARY KEY, code VARCHAR(10) NOT NULL UNIQUE, "
                "name VARCHAR(120) NOT NULL UNIQUE, is_active BOOLEAN NOT NULL, "
                "available_staff INTEGER NOT NULL, default_service_minutes FLOAT NOT NULL)"
            )
            connection.exec_driver_sql(
                "CREATE TABLE registration_sessions ("
                "id VARCHAR(36) PRIMARY KEY, session_date DATE NOT NULL UNIQUE)"
            )
            connection.exec_driver_sql(
                "CREATE TABLE legacy_booking_refs ("
                "session_id VARCHAR(36) REFERENCES registration_sessions(id))"
            )
            connection.exec_driver_sql(
                "INSERT INTO departments "
                "(id, code, name, is_active, available_staff, default_service_minutes) "
                "VALUES ('dept-1', 'GEN', 'General', 1, 2, 15), "
                "('dept-2', 'CAR', 'Cardiology', 1, 2, 15)"
            )
            connection.exec_driver_sql(
                "INSERT INTO registration_sessions (id, session_date) "
                "VALUES ('session-old', '2026-10-14')"
            )
            connection.exec_driver_sql(
                "INSERT INTO legacy_booking_refs (session_id) VALUES ('session-old')"
            )

        migrate_sqlite_schema(engine)

        constraints = inspect(engine).get_unique_constraints("registration_sessions")
        assert not any(item.get("column_names") == ["session_date"] for item in constraints)
        assert any(
            set(item.get("column_names", [])) == {"department_id", "session_date"}
            for item in constraints
        )
        with engine.connect() as connection:
            assert connection.scalar(text("SELECT id FROM registration_sessions")) == "session-old"
            assert connection.scalar(text("SELECT session_id FROM legacy_booking_refs")) == "session-old"

        with Session(engine) as session:
            session.add_all([
                RegistrationSession(
                    id="session-dept-1",
                    department_id="dept-1",
                    session_date=date(2026, 10, 14),
                ),
                RegistrationSession(
                    id="session-dept-2",
                    department_id="dept-2",
                    session_date=date(2026, 10, 14),
                ),
            ])
            session.commit()
    finally:
        engine.dispose()
