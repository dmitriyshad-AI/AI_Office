"""policy engine

Revision ID: 20260308_0003
Revises: 20260308_0002
Create Date: 2026-03-08 02:30:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "20260308_0003"
down_revision = "20260308_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "approval_policies",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("action_key", sa.String(length=120), nullable=False),
        sa.Column("scope", sa.String(length=80), nullable=False),
        sa.Column("default_risk_level", sa.String(length=50), nullable=False),
        sa.Column("approval_mode", sa.String(length=50), nullable=False),
        sa.Column("allowed_roles", sa.JSON(), nullable=False),
        sa.Column("allowlist", sa.JSON(), nullable=False),
        sa.Column("denylist", sa.JSON(), nullable=False),
        sa.Column("rationale", sa.Text(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "risk_assessments",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("task_id", sa.String(length=36), nullable=True),
        sa.Column("approval_policy_id", sa.String(length=36), nullable=True),
        sa.Column("action_key", sa.String(length=120), nullable=False),
        sa.Column("requested_by", sa.String(length=120), nullable=False),
        sa.Column("risk_level", sa.String(length=50), nullable=False),
        sa.Column("approval_mode", sa.String(length=50), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("rationale", sa.Text(), nullable=False),
        sa.Column("details", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["approval_policy_id"], ["approval_policies.id"]),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.id"]),
        sa.PrimaryKeyConstraint("id"),
    )

    op.add_column(
        "approval_requests",
        sa.Column("approval_policy_id", sa.String(length=36), nullable=True),
    )
    op.add_column(
        "approval_requests",
        sa.Column("risk_assessment_id", sa.String(length=36), nullable=True),
    )
    op.create_foreign_key(
        "fk_approval_requests_policy",
        "approval_requests",
        "approval_policies",
        ["approval_policy_id"],
        ["id"],
    )
    op.create_foreign_key(
        "fk_approval_requests_assessment",
        "approval_requests",
        "risk_assessments",
        ["risk_assessment_id"],
        ["id"],
    )

    op.create_table(
        "approval_decisions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("task_id", sa.String(length=36), nullable=True),
        sa.Column("risk_assessment_id", sa.String(length=36), nullable=False),
        sa.Column("approval_request_id", sa.String(length=36), nullable=True),
        sa.Column("action_key", sa.String(length=120), nullable=False),
        sa.Column("risk_level", sa.String(length=50), nullable=False),
        sa.Column("actor", sa.String(length=120), nullable=False),
        sa.Column("outcome", sa.String(length=50), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["approval_request_id"], ["approval_requests.id"]),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.ForeignKeyConstraint(["risk_assessment_id"], ["risk_assessments.id"]),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.id"]),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("approval_decisions")
    op.drop_constraint("fk_approval_requests_assessment", "approval_requests", type_="foreignkey")
    op.drop_constraint("fk_approval_requests_policy", "approval_requests", type_="foreignkey")
    op.drop_column("approval_requests", "risk_assessment_id")
    op.drop_column("approval_requests", "approval_policy_id")
    op.drop_table("risk_assessments")
    op.drop_table("approval_policies")
