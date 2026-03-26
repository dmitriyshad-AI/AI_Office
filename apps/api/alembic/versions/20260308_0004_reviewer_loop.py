"""reviewer loop

Revision ID: 20260308_0004
Revises: 20260308_0003
Create Date: 2026-03-08 04:10:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "20260308_0004"
down_revision = "20260308_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "task_reviews",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("task_id", sa.String(length=36), nullable=False),
        sa.Column("task_run_id", sa.String(length=36), nullable=True),
        sa.Column("reviewer_agent_id", sa.String(length=36), nullable=True),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("recommendation", sa.String(length=50), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("severity_counts", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.ForeignKeyConstraint(["reviewer_agent_id"], ["agents.id"]),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.id"]),
        sa.ForeignKeyConstraint(["task_run_id"], ["task_runs.id"]),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "review_findings",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("task_id", sa.String(length=36), nullable=False),
        sa.Column("task_review_id", sa.String(length=36), nullable=False),
        sa.Column("severity", sa.String(length=50), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("details", sa.Text(), nullable=False),
        sa.Column("suggested_fix", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.id"]),
        sa.ForeignKeyConstraint(["task_review_id"], ["task_reviews.id"]),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("review_findings")
    op.drop_table("task_reviews")
