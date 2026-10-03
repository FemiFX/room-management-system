"""add internal room assignments

Revision ID: 20260409_0008
Revises: 20260409_0007
Create Date: 2026-04-09
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

from app.db.migration_helpers import has_index, has_table

revision = "20260409_0008"
down_revision = "20260409_0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Guarded: 0001 runs create_all, so this table and its indexes exist on a
    # fresh database.
    if has_table("internal_room_assignments"):
        _create_missing_indexes()
        return

    op.create_table(
        "internal_room_assignments",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("room_id", sa.Integer(), sa.ForeignKey("rooms.id"), nullable=False),
        sa.Column("party_id", sa.Integer(), sa.ForeignKey("parties.id"), nullable=False),
        sa.Column("assigned_by_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    _create_missing_indexes()


def _create_missing_indexes() -> None:
    if not has_index("internal_room_assignments", "uq_internal_room_assignments_active_room"):
        op.create_index(
            "uq_internal_room_assignments_active_room",
            "internal_room_assignments",
            ["room_id"],
            unique=True,
            postgresql_where=sa.text("end_date IS NULL"),
            sqlite_where=sa.text("end_date IS NULL"),
        )
    for column in ("room_id", "party_id", "assigned_by_user_id"):
        name = f"ix_internal_room_assignments_{column}"
        if not has_index("internal_room_assignments", name):
            op.create_index(name, "internal_room_assignments", [column], unique=False)


def downgrade() -> None:
    op.drop_index("ix_internal_room_assignments_assigned_by_user_id", table_name="internal_room_assignments")
    op.drop_index("ix_internal_room_assignments_party_id", table_name="internal_room_assignments")
    op.drop_index("ix_internal_room_assignments_room_id", table_name="internal_room_assignments")
    op.drop_index("uq_internal_room_assignments_active_room", table_name="internal_room_assignments")
    op.drop_table("internal_room_assignments")
