"""action intents

Revision ID: 20260308_0006
Revises: 20260308_0005
Create Date: 2026-03-08 05:55:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "20260308_0006"
down_revision = "20260308_0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "action_intents",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("task_id", sa.String(length=36), nullable=True),
        sa.Column("task_run_id", sa.String(length=36), nullable=True),
        sa.Column("approval_request_id", sa.String(length=36), nullable=True),
        sa.Column("action_key", sa.String(length=120), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("requested_by", sa.String(length=120), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("execution_summary", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["approval_request_id"], ["approval_requests.id"]),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.id"]),
        sa.ForeignKeyConstraint(["task_run_id"], ["task_runs.id"]),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("action_intents")
