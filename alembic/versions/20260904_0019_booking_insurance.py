"""liability insurance answer and documents attached to a booking

Revision ID: 20260904_0019
Revises: 20260904_0018
Create Date: 2026-09-04

Two additive columns, both nullable:

* ``booking_requests.liability_insurance`` -- the public form's yes/no answer.
  NULL is a third state and the right default for every existing row: staff
  and portal bookings are never asked the question, so "not answered" is the
  truth about them, not "no".
* ``documents.booking_id`` -- documents already hang off a room or a lease;
  a booking is the same kind of parent. This is what an insurance certificate
  attaches to.
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

from app.db.migration_helpers import has_column, has_index

revision = "20260904_0019"
down_revision = "20260904_0018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Guarded: 0001 runs create_all, so on a fresh database the models have
    # already produced both of these.
    if not has_column("booking_requests", "liability_insurance"):
        op.add_column(
            "booking_requests",
            sa.Column("liability_insurance", sa.Boolean(), nullable=True),
        )
    if not has_column("documents", "booking_id"):
        op.add_column("documents", sa.Column("booking_id", sa.Integer(), nullable=True))
        op.create_foreign_key(
            "fk_documents_booking_id", "documents", "bookings", ["booking_id"], ["id"]
        )
    if not has_index("documents", "ix_documents_booking_id"):
        op.create_index("ix_documents_booking_id", "documents", ["booking_id"])


def downgrade() -> None:
    if has_index("documents", "ix_documents_booking_id"):
        op.drop_index("ix_documents_booking_id", table_name="documents")
    if has_column("documents", "booking_id"):
        op.drop_constraint("fk_documents_booking_id", "documents", type_="foreignkey")
        op.drop_column("documents", "booking_id")
    if has_column("booking_requests", "liability_insurance"):
        op.drop_column("booking_requests", "liability_insurance")
