"""link users to parties and nextcloud accounts

Revision ID: 20260828_0015
Revises: 20260828_0014
Create Date: 2026-08-28
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

from app.db.migration_helpers import has_column, has_index

revision = "20260828_0015"
down_revision = "20260828_0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if not has_column("users", "party_id"):
        op.add_column("users", sa.Column("party_id", sa.Integer(), sa.ForeignKey("parties.id"), nullable=True))
    if not has_column("users", "nc_user_id"):
        op.add_column("users", sa.Column("nc_user_id", sa.String(length=255), nullable=True))

    # Partial: most users have neither, and a plain UNIQUE would collide on
    # NULL under some dialects. Same pattern as 0008.
    if not has_index("users", "uq_users_party_id"):
        op.create_index(
            "uq_users_party_id",
            "users",
            ["party_id"],
            unique=True,
            postgresql_where=sa.text("party_id IS NOT NULL"),
            sqlite_where=sa.text("party_id IS NOT NULL"),
        )
    if not has_index("users", "uq_users_nc_user_id"):
        op.create_index(
            "uq_users_nc_user_id",
            "users",
            ["nc_user_id"],
            unique=True,
            postgresql_where=sa.text("nc_user_id IS NOT NULL"),
            sqlite_where=sa.text("nc_user_id IS NOT NULL"),
        )


def downgrade() -> None:
    op.drop_index("uq_users_nc_user_id", table_name="users")
    op.drop_index("uq_users_party_id", table_name="users")
    op.drop_column("users", "nc_user_id")
    op.drop_column("users", "party_id")
