"""crm bridge preview

Revision ID: 20260309_0010
Revises: 20260308_0009
Create Date: 2026-03-09 16:20:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "20260309_0010"
down_revision = "20260308_0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "crm_sync_previews",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("source_student_id", sa.String(length=120), nullable=False),
        sa.Column("source_system", sa.String(length=80), nullable=False),
        sa.Column("amo_entity_type", sa.String(length=50), nullable=False),
        sa.Column("amo_entity_id", sa.String(length=120), nullable=True),
        sa.Column("source_payload", sa.JSON(), nullable=False),
        sa.Column("canonical_payload", sa.JSON(), nullable=False),
        sa.Column("amo_field_payload", sa.JSON(), nullable=False),
        sa.Column("field_mapping", sa.JSON(), nullable=False),
        sa.Column("analysis_summary", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("created_by", sa.String(length=120), nullable=False),
        sa.Column("sent_by", sa.String(length=120), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("send_result", sa.JSON(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_crm_sync_previews_project_id",
        "crm_sync_previews",
        ["project_id"],
        unique=False,
    )
    op.create_index(
        "ix_crm_sync_previews_source_student_id",
        "crm_sync_previews",
        ["source_student_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_crm_sync_previews_source_student_id", table_name="crm_sync_previews")
    op.drop_index("ix_crm_sync_previews_project_id", table_name="crm_sync_previews")
    op.drop_table("crm_sync_previews")
