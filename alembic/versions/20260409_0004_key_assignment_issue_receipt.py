"""add key assignment issue receipt metadata

Revision ID: 20260409_0004
Revises: 20260326_0003
Create Date: 2026-04-09
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

from app.db.migration_helpers import has_column

revision = "20260409_0004"
down_revision = "20260326_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Guarded: 0001 runs create_all, so these columns exist on a fresh database.
    columns = [
        sa.Column("issue_receipt_object_key", sa.String(length=255), nullable=True),
        sa.Column("issue_receipt_filename", sa.String(length=255), nullable=True),
        sa.Column("issue_receipt_mime_type", sa.String(length=120), nullable=True),
        sa.Column("issue_receipt_size", sa.Integer(), nullable=True),
    ]
    missing = [column for column in columns if not has_column("key_assignments", column.name)]
    if missing:
        with op.batch_alter_table("key_assignments") as batch_op:
            for column in missing:
                batch_op.add_column(column)


def downgrade() -> None:
    with op.batch_alter_table("key_assignments") as batch_op:
        batch_op.drop_column("issue_receipt_size")
        batch_op.drop_column("issue_receipt_mime_type")
        batch_op.drop_column("issue_receipt_filename")
        batch_op.drop_column("issue_receipt_object_key")
