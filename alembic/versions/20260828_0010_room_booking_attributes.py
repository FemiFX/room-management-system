"""add public booking attributes to rooms

Revision ID: 20260828_0010
Revises: 20260410_0009
Create Date: 2026-08-28
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

from app.db.migration_helpers import has_column, has_index

revision = "20260828_0010"
down_revision = "20260410_0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Additive only. public_bookable keeps its server_default so any
    # out-of-band insert stays valid; on PG 11+ adding a NOT NULL column with a
    # constant default is metadata-only, so no table rewrite.
    if not has_column("rooms", "public_bookable"):
        op.add_column(
            "rooms",
            sa.Column("public_bookable", sa.Boolean(), nullable=False, server_default=sa.false()),
        )
    if not has_column("rooms", "capacity"):
        op.add_column("rooms", sa.Column("capacity", sa.Integer(), nullable=True))
    if not has_column("rooms", "public_description"):
        op.add_column("rooms", sa.Column("public_description", sa.Text(), nullable=True))
    if not has_column("rooms", "cleaning_rate_daily"):
        op.add_column("rooms", sa.Column("cleaning_rate_daily", sa.Numeric(10, 2), nullable=True))
    if not has_index("rooms", "ix_rooms_public_bookable"):
        op.create_index("ix_rooms_public_bookable", "rooms", ["public_bookable"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_rooms_public_bookable", table_name="rooms")
    op.drop_column("rooms", "cleaning_rate_daily")
    op.drop_column("rooms", "public_description")
    op.drop_column("rooms", "capacity")
    op.drop_column("rooms", "public_bookable")
