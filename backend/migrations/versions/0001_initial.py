"""Initial FlowCare tables.

Revision ID: 0001_initial
Revises:
"""
from alembic import op
import sqlalchemy as sa

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "users",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("email", sa.String(255), nullable=False, unique=True),
        sa.Column("display_name", sa.String(120), nullable=False),
        sa.Column("role", sa.String(30), nullable=False),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_users_email", "users", ["email"], unique=True)
    op.create_table(
        "departments",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("code", sa.String(10), nullable=False, unique=True),
        sa.Column("name", sa.String(120), nullable=False, unique=True),
        sa.Column("available_staff", sa.Integer(), nullable=False),
        sa.Column("default_service_minutes", sa.Float(), nullable=False),
    )
    op.create_table(
        "patients",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("reference", sa.String(40), nullable=False, unique=True),
        sa.Column("display_name", sa.String(120)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_patients_reference", "patients", ["reference"], unique=True)
    op.create_table(
        "queue_tickets",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("patient_id", sa.String(36), sa.ForeignKey("patients.id"), nullable=False),
        sa.Column("department_id", sa.String(36), sa.ForeignKey("departments.id"), nullable=False),
        sa.Column("token_day", sa.String(10), nullable=False),
        sa.Column("token_number", sa.Integer(), nullable=False),
        sa.Column("appointment_type", sa.String(20), nullable=False),
        sa.Column("is_appointment", sa.Boolean(), nullable=False),
        sa.Column("priority", sa.String(20), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("arrival_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("service_started_at", sa.DateTime(timezone=True)),
        sa.Column("service_completed_at", sa.DateTime(timezone=True)),
        sa.Column("expected_service_minutes", sa.Float(), nullable=False),
        sa.UniqueConstraint("department_id", "token_day", "token_number", name="uq_department_daily_token"),
    )
    op.create_index("ix_queue_tickets_patient_id", "queue_tickets", ["patient_id"])
    op.create_index("ix_queue_tickets_department_id", "queue_tickets", ["department_id"])
    op.create_index("ix_queue_tickets_status", "queue_tickets", ["status"])
    op.create_index("ix_ticket_department_status", "queue_tickets", ["department_id", "status"])
    op.create_table(
        "queue_events",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("ticket_id", sa.String(36), sa.ForeignKey("queue_tickets.id"), nullable=False),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id")),
        sa.Column("from_status", sa.String(20)),
        sa.Column("to_status", sa.String(20), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_queue_events_ticket_id", "queue_events", ["ticket_id"])
    op.create_table(
        "prediction_records",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("ticket_id", sa.String(36), sa.ForeignKey("queue_tickets.id"), nullable=False),
        sa.Column("predicted_minutes", sa.Float(), nullable=True),
        sa.Column("model", sa.String(60), nullable=False),
        sa.Column("input_snapshot", sa.Text(), nullable=False),
        sa.Column("predicted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("actual_wait_minutes", sa.Float()),
    )
    op.create_index("ix_prediction_records_ticket_id", "prediction_records", ["ticket_id"])
    op.create_table(
        "simulation_records",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("seed", sa.Integer(), nullable=False),
        sa.Column("parameters", sa.Text(), nullable=False),
        sa.Column("results", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "audit_logs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id")),
        sa.Column("action", sa.String(100), nullable=False),
        sa.Column("resource_type", sa.String(50), nullable=False),
        sa.Column("resource_id", sa.String(36)),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade():
    op.drop_table("audit_logs")
    op.drop_table("simulation_records")
    op.drop_index("ix_prediction_records_ticket_id", table_name="prediction_records")
    op.drop_table("prediction_records")
    op.drop_index("ix_queue_events_ticket_id", table_name="queue_events")
    op.drop_table("queue_events")
    op.drop_index("ix_ticket_department_status", table_name="queue_tickets")
    op.drop_index("ix_queue_tickets_status", table_name="queue_tickets")
    op.drop_index("ix_queue_tickets_department_id", table_name="queue_tickets")
    op.drop_index("ix_queue_tickets_patient_id", table_name="queue_tickets")
    op.drop_table("queue_tickets")
    op.drop_index("ix_patients_reference", table_name="patients")
    op.drop_table("patients")
    op.drop_table("departments")
    op.drop_index("ix_users_email", table_name="users")
    op.drop_table("users")
