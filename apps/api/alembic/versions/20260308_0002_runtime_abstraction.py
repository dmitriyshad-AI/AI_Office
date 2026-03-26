"""runtime abstraction

Revision ID: 20260308_0002
Revises: 20260308_0001
Create Date: 2026-03-08 00:30:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "20260308_0002"
down_revision = "20260308_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "task_workspaces",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("task_id", sa.String(length=36), nullable=False),
        sa.Column("root_path", sa.String(length=255), nullable=False),
        sa.Column("workspace_path", sa.String(length=255), nullable=False),
        sa.Column("sandbox_mode", sa.String(length=50), nullable=False),
        sa.Column("state", sa.String(length=50), nullable=False),
        sa.Column("context_file_path", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("task_id"),
    )

    op.create_table(
        "task_environments",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("task_id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("runtime_kind", sa.String(length=80), nullable=False),
        sa.Column("base_image", sa.String(length=120), nullable=False),
        sa.Column("env_vars", sa.JSON(), nullable=False),
        sa.Column("mounts", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("task_id"),
    )

    op.create_table(
        "run_policies",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("task_id", sa.String(length=36), nullable=False),
        sa.Column("policy_level", sa.String(length=50), nullable=False),
        sa.Column("network_access", sa.String(length=50), nullable=False),
        sa.Column("filesystem_scope", sa.String(length=80), nullable=False),
        sa.Column("package_installation_mode", sa.String(length=80), nullable=False),
        sa.Column("default_risk_level", sa.String(length=50), nullable=False),
        sa.Column("notes", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("task_id"),
    )


def downgrade() -> None:
    op.drop_table("run_policies")
    op.drop_table("task_environments")
    op.drop_table("task_workspaces")
