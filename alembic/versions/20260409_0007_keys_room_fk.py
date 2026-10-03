"""add optional room link to keys

Revision ID: 20260409_0007
Revises: 20260409_0006
Create Date: 2026-04-09 12:30:00
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

from app.db.migration_helpers import has_column, has_foreign_key_on, has_index

revision: str = "20260409_0007"
down_revision: str | None = "20260409_0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Guarded: 0001 runs create_all, so the column, its index and an
    # equivalent (auto-named) foreign key exist on a fresh database.
    if not has_column("keys", "room_id"):
        op.add_column("keys", sa.Column("room_id", sa.Integer(), nullable=True))
    if not has_index("keys", op.f("ix_keys_room_id")):
        op.create_index(op.f("ix_keys_room_id"), "keys", ["room_id"], unique=False)
    if not has_foreign_key_on("keys", "room_id", referred_table="rooms"):
        op.create_foreign_key(
            "fk_keys_room_id_rooms",
            "keys",
            "rooms",
            ["room_id"],
            ["id"],
            ondelete="SET NULL",
        )


def downgrade() -> None:
    op.drop_constraint("fk_keys_room_id_rooms", "keys", type_="foreignkey")
    op.drop_index(op.f("ix_keys_room_id"), table_name="keys")
    op.drop_column("keys", "room_id")
