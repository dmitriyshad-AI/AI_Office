"""approval resolution

Revision ID: 20260308_0005
Revises: 20260308_0004
Create Date: 2026-03-08 05:10:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "20260308_0005"
down_revision = "20260308_0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "approval_requests",
        sa.Column("resolved_by", sa.String(length=120), nullable=True),
    )
    op.add_column(
        "approval_requests",
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "approval_requests",
        sa.Column("resolution_summary", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("approval_requests", "resolution_summary")
    op.drop_column("approval_requests", "resolved_at")
    op.drop_column("approval_requests", "resolved_by")
