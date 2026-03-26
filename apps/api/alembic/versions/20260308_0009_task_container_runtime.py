"""task container runtime

Revision ID: 20260308_0009
Revises: 20260308_0008
Create Date: 2026-03-08 17:10:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "20260308_0009"
down_revision = "20260308_0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "task_environments",
        sa.Column("container_name", sa.String(length=160), nullable=True),
    )
    op.add_column(
        "task_environments",
        sa.Column("container_id", sa.String(length=160), nullable=True),
    )
    op.add_column(
        "task_environments",
        sa.Column("container_workdir", sa.String(length=255), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("task_environments", "container_workdir")
    op.drop_column("task_environments", "container_id")
    op.drop_column("task_environments", "container_name")
