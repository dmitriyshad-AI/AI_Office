"""review queue and controlled write state

Revision ID: 20260320_0012
Revises: 20260319_0011
Create Date: 2026-03-20 10:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "20260320_0012"
down_revision = "20260319_0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "crm_sync_previews",
        sa.Column("review_status", sa.String(length=32), nullable=False, server_default="not_required"),
    )
    op.add_column("crm_sync_previews", sa.Column("review_reason", sa.Text(), nullable=True))
    op.add_column("crm_sync_previews", sa.Column("review_summary", sa.Text(), nullable=True))
    op.add_column("crm_sync_previews", sa.Column("reviewed_by", sa.String(length=120), nullable=True))
    op.add_column("crm_sync_previews", sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True))

    op.add_column(
        "call_insights",
        sa.Column("review_status", sa.String(length=32), nullable=False, server_default="pending"),
    )
    op.add_column("call_insights", sa.Column("review_summary", sa.Text(), nullable=True))
    op.add_column("call_insights", sa.Column("reviewed_by", sa.String(length=120), nullable=True))
    op.add_column("call_insights", sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("call_insights", sa.Column("sent_by", sa.String(length=120), nullable=True))
    op.add_column("call_insights", sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("call_insights", sa.Column("send_result", sa.JSON(), nullable=True))
    op.add_column("call_insights", sa.Column("error_message", sa.Text(), nullable=True))

    op.alter_column("crm_sync_previews", "review_status", server_default=None)
    op.alter_column("call_insights", "review_status", server_default=None)


def downgrade() -> None:
    op.drop_column("call_insights", "error_message")
    op.drop_column("call_insights", "send_result")
    op.drop_column("call_insights", "sent_at")
    op.drop_column("call_insights", "sent_by")
    op.drop_column("call_insights", "reviewed_at")
    op.drop_column("call_insights", "reviewed_by")
    op.drop_column("call_insights", "review_summary")
    op.drop_column("call_insights", "review_status")

    op.drop_column("crm_sync_previews", "reviewed_at")
    op.drop_column("crm_sync_previews", "reviewed_by")
    op.drop_column("crm_sync_previews", "review_summary")
    op.drop_column("crm_sync_previews", "review_reason")
    op.drop_column("crm_sync_previews", "review_status")
