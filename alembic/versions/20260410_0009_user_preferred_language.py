"""add users preferred language

Revision ID: 20260410_0009
Revises: 20260409_0008
Create Date: 2026-04-10
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

from app.db.migration_helpers import has_column

revision = "20260410_0009"
down_revision = "20260409_0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Guarded: 0001 runs create_all, so this column exists on a fresh database.
    if not has_column("users", "preferred_language"):
        op.add_column(
            "users",
            sa.Column("preferred_language", sa.String(length=8), nullable=False, server_default="de"),
        )
        op.alter_column("users", "preferred_language", server_default=None)


def downgrade() -> None:
    op.drop_column("users", "preferred_language")
