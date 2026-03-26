"""runtime isolation metadata

Revision ID: 20260308_0008
Revises: 20260308_0007
Create Date: 2026-03-08 04:30:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "20260308_0008"
down_revision = "20260308_0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "task_workspaces",
        sa.Column("source_root_path", sa.String(length=255), nullable=True),
    )
    op.add_column(
        "task_workspaces",
        sa.Column(
            "workspace_mode",
            sa.String(length=50),
            nullable=False,
            server_default="snapshot-copy",
        ),
    )
    op.add_column(
        "task_workspaces",
        sa.Column(
            "sync_status",
            sa.String(length=50),
            nullable=False,
            server_default="seeded",
        ),
    )
    op.add_column(
        "task_environments",
        sa.Column(
            "runtime_status",
            sa.String(length=50),
            nullable=False,
            server_default="ready",
        ),
    )
    op.add_column(
        "task_environments",
        sa.Column(
            "source_mount_mode",
            sa.String(length=80),
            nullable=False,
            server_default="read-only",
        ),
    )
    op.add_column(
        "task_environments",
        sa.Column(
            "workspace_mount_mode",
            sa.String(length=80),
            nullable=False,
            server_default="read-write",
        ),
    )
    op.add_column(
        "task_environments",
        sa.Column(
            "network_mode",
            sa.String(length=80),
            nullable=False,
            server_default="restricted",
        ),
    )


def downgrade() -> None:
    op.drop_column("task_environments", "network_mode")
    op.drop_column("task_environments", "workspace_mount_mode")
    op.drop_column("task_environments", "source_mount_mode")
    op.drop_column("task_environments", "runtime_status")
    op.drop_column("task_workspaces", "sync_status")
    op.drop_column("task_workspaces", "workspace_mode")
    op.drop_column("task_workspaces", "source_root_path")
