"""add nextcloud user mapping to parties

Revision ID: 20260409_0005
Revises: 20260409_0004
Create Date: 2026-04-09
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

from app.db.migration_helpers import has_column, has_index

revision = "20260409_0005"
down_revision = "20260409_0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Guarded: 0001 runs create_all, so this column and index exist on a fresh
    # database.
    add_column = not has_column("parties", "nc_user_id")
    add_index = not has_index("parties", "ix_parties_nc_user_id")
    if add_column or add_index:
        with op.batch_alter_table("parties") as batch_op:
            if add_column:
                batch_op.add_column(sa.Column("nc_user_id", sa.String(length=255), nullable=True))
            if add_index:
                batch_op.create_index("ix_parties_nc_user_id", ["nc_user_id"], unique=True)


def downgrade() -> None:
    with op.batch_alter_table("parties") as batch_op:
        batch_op.drop_index("ix_parties_nc_user_id")
        batch_op.drop_column("nc_user_id")
