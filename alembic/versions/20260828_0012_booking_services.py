"""add booking services catalogue

Revision ID: 20260828_0012
Revises: 20260828_0011
Create Date: 2026-08-28
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

from app.db.migration_helpers import has_index, has_table

revision = "20260828_0012"
down_revision = "20260828_0011"
branch_labels = None
depends_on = None

#: Seeded so the feature is usable on day one. Populating a brand-new empty
#: table is not a backfill -- no existing row is touched.
_SEED = [
    {"code": "technician", "name": "Technician", "is_active": True, "sort_order": 10},
    {"code": "usher", "name": "Usher", "is_active": True, "sort_order": 20},
]


def upgrade() -> None:
    created = False
    if not has_table("booking_services"):
        op.create_table(
            "booking_services",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("code", sa.String(length=50), nullable=False),
            sa.Column("name", sa.String(length=150), nullable=False),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        )
        created = True
    if not has_index("booking_services", "ix_booking_services_code"):
        op.create_index("ix_booking_services_code", "booking_services", ["code"], unique=True)

    # Seed only when this migration created the table, and only if it is empty
    # -- re-running against a populated catalogue must not duplicate rows.
    bind = op.get_bind()
    existing = bind.execute(sa.text("SELECT COUNT(*) FROM booking_services")).scalar() or 0
    if existing == 0:
        table = sa.table(
            "booking_services",
            sa.column("code", sa.String),
            sa.column("name", sa.String),
            sa.column("is_active", sa.Boolean),
            sa.column("sort_order", sa.Integer),
        )
        op.bulk_insert(table, _SEED)


def downgrade() -> None:
    op.drop_index("ix_booking_services_code", table_name="booking_services")
    op.drop_table("booking_services")
