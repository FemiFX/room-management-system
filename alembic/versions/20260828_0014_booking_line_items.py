"""add booking equipment and service line items

Revision ID: 20260828_0014
Revises: 20260828_0013
Create Date: 2026-08-28
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

from app.db.migration_helpers import has_index, has_table

revision = "20260828_0014"
down_revision = "20260828_0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if not has_table("booking_equipment_requests"):
        op.create_table(
            "booking_equipment_requests",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column(
                "booking_id", sa.Integer(), sa.ForeignKey("bookings.id", ondelete="CASCADE"), nullable=False
            ),
            sa.Column("equipment_id", sa.Integer(), sa.ForeignKey("equipment.id"), nullable=False),
            sa.Column("quantity", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("notes", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.UniqueConstraint("booking_id", "equipment_id", name="uq_booking_equipment_request"),
        )
    if not has_table("booking_service_requests"):
        op.create_table(
            "booking_service_requests",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column(
                "booking_id", sa.Integer(), sa.ForeignKey("bookings.id", ondelete="CASCADE"), nullable=False
            ),
            sa.Column("service_id", sa.Integer(), sa.ForeignKey("booking_services.id"), nullable=False),
            sa.Column("quantity", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.UniqueConstraint("booking_id", "service_id", name="uq_booking_service_request"),
        )
    for table, column in (
        ("booking_equipment_requests", "booking_id"),
        ("booking_equipment_requests", "equipment_id"),
        ("booking_service_requests", "booking_id"),
        ("booking_service_requests", "service_id"),
    ):
        name = f"ix_{table}_{column}"
        if not has_index(table, name):
            op.create_index(name, table, [column], unique=False)


def downgrade() -> None:
    op.drop_table("booking_service_requests")
    op.drop_table("booking_equipment_requests")
