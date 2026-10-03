"""offer booking services per room

Revision ID: 20260903_0017
Revises: 20260828_0016
Create Date: 2026-09-03

Services were global: every active service showed on the public form for
every room. This adds the same per-room link table equipment already has.

Purely additive -- a new table plus a backfill that INSERTS one row per
(active room x active service). The backfill is what makes this a no-op for
existing behaviour: without it, creating the table would silently stop every
room offering anything.
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

from app.db.migration_helpers import has_index, has_table

revision = "20260903_0017"
down_revision = "20260828_0016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Guarded: 0001 runs create_all, so on a fresh database this table already
    # exists. The backfill below still runs -- it is idempotent on a fresh
    # database because there is nothing to select.
    if not has_table("room_services"):
        op.create_table(
            "room_services",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("room_id", sa.Integer(), nullable=False),
            sa.Column("service_id", sa.Integer(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.ForeignKeyConstraint(["room_id"], ["rooms.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["service_id"], ["booking_services.id"], ondelete="CASCADE"),
            sa.UniqueConstraint("room_id", "service_id", name="uq_room_service"),
        )
    if not has_index("room_services", "ix_room_services_room_id"):
        op.create_index("ix_room_services_room_id", "room_services", ["room_id"])
    if not has_index("room_services", "ix_room_services_service_id"):
        op.create_index("ix_room_services_service_id", "room_services", ["service_id"])

    # Reproduce the old "every service, every room" behaviour so no existing
    # room silently loses its services on deploy. NOT EXISTS keeps it safe to
    # re-run, and `is_active` is compared against a bound literal rather than
    # `true` so the statement works on SQLite as well as PostgreSQL.
    op.execute(
        sa.text(
            """
            INSERT INTO room_services (room_id, service_id)
            SELECT r.id, s.id
              FROM rooms r
             CROSS JOIN booking_services s
             WHERE r.is_active = :yes
               AND s.is_active = :yes
               AND NOT EXISTS (
                   SELECT 1 FROM room_services rs
                    WHERE rs.room_id = r.id AND rs.service_id = s.id
               )
            """
        ).bindparams(yes=True)
    )


def downgrade() -> None:
    if has_index("room_services", "ix_room_services_service_id"):
        op.drop_index("ix_room_services_service_id", table_name="room_services")
    if has_index("room_services", "ix_room_services_room_id"):
        op.drop_index("ix_room_services_room_id", table_name="room_services")
    if has_table("room_services"):
        op.drop_table("room_services")
