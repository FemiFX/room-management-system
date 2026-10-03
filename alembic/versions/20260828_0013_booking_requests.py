"""add booking request envelope

Revision ID: 20260828_0013
Revises: 20260828_0012
Create Date: 2026-08-28
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

from app.db.migration_helpers import has_index, has_table

revision = "20260828_0013"
down_revision = "20260828_0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if not has_table("booking_requests"):
        op.create_table(
            "booking_requests",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column(
                "booking_id",
                sa.Integer(),
                sa.ForeignKey("bookings.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("public_ref", sa.String(length=24), nullable=False),
            sa.Column("token_version", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("language", sa.String(length=8), nullable=False, server_default="de"),
            sa.Column("requester_first_name", sa.String(length=150), nullable=True),
            sa.Column("requester_last_name", sa.String(length=150), nullable=True),
            sa.Column("requester_academic_title", sa.String(length=100), nullable=True),
            sa.Column("requester_organization", sa.String(length=255), nullable=True),
            sa.Column("requester_email", sa.String(length=255), nullable=True),
            sa.Column("requester_phone", sa.String(length=100), nullable=True),
            sa.Column("requester_address", sa.Text(), nullable=True),
            sa.Column("contact_person", sa.String(length=255), nullable=True),
            sa.Column("billing_info", sa.Text(), nullable=True),
            sa.Column("additional_info", sa.Text(), nullable=True),
            sa.Column("whole_day", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("cleaning_rate_daily", sa.Numeric(10, 2), nullable=True),
            sa.Column("cleaning_days", sa.Integer(), nullable=True),
            sa.Column("cleaning_charge", sa.Numeric(10, 2), nullable=True),
            sa.Column("currency", sa.String(length=3), nullable=False, server_default="EUR"),
            sa.Column("staff_note", sa.Text(), nullable=True),
            sa.Column("submitted_ip_hash", sa.String(length=64), nullable=True),
            sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("cancelled_by", sa.String(length=20), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        )
    for name, columns, unique in (
        ("ix_booking_requests_booking_id", ["booking_id"], True),
        ("ix_booking_requests_public_ref", ["public_ref"], True),
        ("ix_booking_requests_requester_email", ["requester_email"], False),
    ):
        if not has_index("booking_requests", name):
            op.create_index(name, "booking_requests", columns, unique=unique)


def downgrade() -> None:
    op.drop_index("ix_booking_requests_requester_email", table_name="booking_requests")
    op.drop_index("ix_booking_requests_public_ref", table_name="booking_requests")
    op.drop_index("ix_booking_requests_booking_id", table_name="booking_requests")
    op.drop_table("booking_requests")
