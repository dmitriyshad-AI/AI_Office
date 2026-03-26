"""amo external integration state

Revision ID: 20260326_0013
Revises: 20260320_0012
Create Date: 2026-03-26 19:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "20260326_0013"
down_revision = "20260320_0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "amo_integration_connections",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("integration_mode", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("state", sa.String(length=255), nullable=True),
        sa.Column("account_base_url", sa.String(length=255), nullable=True),
        sa.Column("account_subdomain", sa.String(length=120), nullable=True),
        sa.Column("client_id", sa.String(length=255), nullable=True),
        sa.Column("client_secret", sa.Text(), nullable=True),
        sa.Column("redirect_uri", sa.String(length=1024), nullable=True),
        sa.Column("secrets_uri", sa.String(length=1024), nullable=True),
        sa.Column("scopes", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("access_token", sa.Text(), nullable=True),
        sa.Column("refresh_token", sa.Text(), nullable=True),
        sa.Column("token_type", sa.String(length=64), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("authorized_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("last_secrets_payload", sa.JSON(), nullable=True),
        sa.Column("last_callback_payload", sa.JSON(), nullable=True),
        sa.Column("contact_field_catalog", sa.JSON(), nullable=True),
        sa.Column("contact_field_catalog_synced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_amo_integration_connections_state",
        "amo_integration_connections",
        ["state"],
    )
    op.create_index(
        "ix_amo_integration_connections_account_base_url",
        "amo_integration_connections",
        ["account_base_url"],
    )
    op.create_index(
        "ix_amo_integration_connections_client_id",
        "amo_integration_connections",
        ["client_id"],
    )
    op.alter_column("amo_integration_connections", "scopes", server_default=None)


def downgrade() -> None:
    op.drop_index("ix_amo_integration_connections_client_id", table_name="amo_integration_connections")
    op.drop_index("ix_amo_integration_connections_account_base_url", table_name="amo_integration_connections")
    op.drop_index("ix_amo_integration_connections_state", table_name="amo_integration_connections")
    op.drop_table("amo_integration_connections")
