"""add source and creator to bookings

Revision ID: 20260828_0011
Revises: 20260828_0010
Create Date: 2026-08-28
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

from app.db.migration_helpers import has_column, has_index

revision = "20260828_0011"
down_revision = "20260828_0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Existing rows correctly become source='staff' -- every booking made
    # before this feature was made by a staff member through the admin UI.
    if not has_column("bookings", "source"):
        op.add_column(
            "bookings",
            sa.Column("source", sa.String(length=20), nullable=False, server_default="staff"),
        )
    if not has_column("bookings", "created_by_user_id"):
        op.add_column(
            "bookings",
            sa.Column("created_by_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        )
    if not has_index("bookings", "ix_bookings_source"):
        op.create_index("ix_bookings_source", "bookings", ["source"], unique=False)
    if not has_index("bookings", "ix_bookings_created_by_user_id"):
        op.create_index("ix_bookings_created_by_user_id", "bookings", ["created_by_user_id"], unique=False)
    # Serves the conflict predicate, which until now scanned every approved
    # booking for a room in Python.
    if not has_index("bookings", "ix_bookings_room_start_end"):
        op.create_index(
            "ix_bookings_room_start_end",
            "bookings",
            ["room_id", "start_at", "end_at"],
            unique=False,
        )


def downgrade() -> None:
    op.drop_index("ix_bookings_room_start_end", table_name="bookings")
    op.drop_index("ix_bookings_created_by_user_id", table_name="bookings")
    op.drop_index("ix_bookings_source", table_name="bookings")
    op.drop_column("bookings", "created_by_user_id")
    op.drop_column("bookings", "source")
