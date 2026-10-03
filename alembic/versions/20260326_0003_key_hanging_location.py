"""add key hanging location

Revision ID: 20260326_0003
Revises: 20260326_0002
Create Date: 2026-03-26
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

from app.db.migration_helpers import has_column

revision = "20260326_0003"
down_revision = "20260326_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Guarded: 0001 runs create_all, so this column exists on a fresh database.
    if not has_column("keys", "hanging_location"):
        with op.batch_alter_table("keys") as batch_op:
            batch_op.add_column(sa.Column("hanging_location", sa.String(length=120), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("keys") as batch_op:
        batch_op.drop_column("hanging_location")
