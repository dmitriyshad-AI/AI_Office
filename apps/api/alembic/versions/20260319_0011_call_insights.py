"""call insights intake

Revision ID: 20260319_0011
Revises: 20260309_0010
Create Date: 2026-03-19 03:35:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "20260319_0011"
down_revision = "20260309_0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "call_insights",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("source_system", sa.String(length=80), nullable=False),
        sa.Column("source_key", sa.String(length=255), nullable=False),
        sa.Column("source_call_id", sa.String(length=120), nullable=True),
        sa.Column("source_record_id", sa.String(length=120), nullable=True),
        sa.Column("source_file", sa.String(length=1024), nullable=True),
        sa.Column("source_filename", sa.String(length=255), nullable=True),
        sa.Column("phone", sa.String(length=64), nullable=True),
        sa.Column("manager_name", sa.String(length=255), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("duration_sec", sa.Float(), nullable=True),
        sa.Column("history_summary", sa.Text(), nullable=False),
        sa.Column("lead_priority", sa.String(length=32), nullable=True),
        sa.Column("follow_up_score", sa.Integer(), nullable=True),
        sa.Column("processing_status", sa.String(length=32), nullable=True),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("match_status", sa.String(length=50), nullable=False),
        sa.Column("matched_amo_contact_id", sa.Integer(), nullable=True),
        sa.Column("review_reason", sa.Text(), nullable=True),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("created_by", sa.String(length=120), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "project_id",
            "source_system",
            "source_key",
            name="uq_call_insights_project_source_key",
        ),
    )
    op.create_index("ix_call_insights_project_id", "call_insights", ["project_id"], unique=False)
    op.create_index("ix_call_insights_source_system", "call_insights", ["source_system"], unique=False)
    op.create_index("ix_call_insights_source_key", "call_insights", ["source_key"], unique=False)
    op.create_index("ix_call_insights_source_call_id", "call_insights", ["source_call_id"], unique=False)
    op.create_index("ix_call_insights_source_record_id", "call_insights", ["source_record_id"], unique=False)
    op.create_index("ix_call_insights_phone", "call_insights", ["phone"], unique=False)
    op.create_index("ix_call_insights_lead_priority", "call_insights", ["lead_priority"], unique=False)
    op.create_index(
        "ix_call_insights_matched_amo_contact_id",
        "call_insights",
        ["matched_amo_contact_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_call_insights_matched_amo_contact_id", table_name="call_insights")
    op.drop_index("ix_call_insights_lead_priority", table_name="call_insights")
    op.drop_index("ix_call_insights_phone", table_name="call_insights")
    op.drop_index("ix_call_insights_source_record_id", table_name="call_insights")
    op.drop_index("ix_call_insights_source_call_id", table_name="call_insights")
    op.drop_index("ix_call_insights_source_key", table_name="call_insights")
    op.drop_index("ix_call_insights_source_system", table_name="call_insights")
    op.drop_index("ix_call_insights_project_id", table_name="call_insights")
    op.drop_table("call_insights")
