"""action intent dispatcher

Revision ID: 20260308_0007
Revises: 20260308_0006
Create Date: 2026-03-08 06:35:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "20260308_0007"
down_revision = "20260308_0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "action_intents",
        sa.Column("dispatch_task_run_id", sa.String(length=36), nullable=True),
    )
    op.add_column(
        "action_intents",
        sa.Column("dispatcher_kind", sa.String(length=80), nullable=False, server_default="runtime-dispatcher"),
    )
    op.add_column(
        "action_intents",
        sa.Column("last_error", sa.Text(), nullable=True),
    )
    op.add_column(
        "action_intents",
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "action_intents",
        sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="3"),
    )
    op.add_column(
        "action_intents",
        sa.Column("next_retry_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_action_intents_dispatch_task_run",
        "action_intents",
        "task_runs",
        ["dispatch_task_run_id"],
        ["id"],
    )
    op.alter_column("action_intents", "dispatcher_kind", server_default=None)
    op.alter_column("action_intents", "attempt_count", server_default=None)
    op.alter_column("action_intents", "max_attempts", server_default=None)


def downgrade() -> None:
    op.drop_constraint("fk_action_intents_dispatch_task_run", "action_intents", type_="foreignkey")
    op.drop_column("action_intents", "next_retry_at")
    op.drop_column("action_intents", "max_attempts")
    op.drop_column("action_intents", "attempt_count")
    op.drop_column("action_intents", "last_error")
    op.drop_column("action_intents", "dispatcher_kind")
    op.drop_column("action_intents", "dispatch_task_run_id")
