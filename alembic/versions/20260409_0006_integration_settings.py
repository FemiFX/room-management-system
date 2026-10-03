"""add integration settings table

Revision ID: 20260409_0006
Revises: 20260409_0005
Create Date: 2026-04-09
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

from app.db.migration_helpers import has_index, has_table

revision = "20260409_0006"
down_revision = "20260409_0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Guarded: 0001 runs create_all, so this table exists on a fresh database.
    if not has_table("integration_settings"):
        op.create_table(
            "integration_settings",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("key", sa.String(length=120), nullable=False),
            sa.Column("value", sa.Text(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        )
    if not has_index("integration_settings", "ix_integration_settings_key"):
        op.create_index("ix_integration_settings_key", "integration_settings", ["key"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_integration_settings_key", table_name="integration_settings")
    op.drop_table("integration_settings")
