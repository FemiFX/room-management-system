"""add key inventory quantities

Revision ID: 20260326_0002
Revises: 20260323_0001
Create Date: 2026-03-26
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

from app.db.migration_helpers import has_column, has_constraint

revision = "20260326_0002"
down_revision = "20260323_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Guarded because 0001 runs create_all: on a fresh database these columns
    # and constraints already exist. See app/db/migration_helpers.py.
    added = [
        (name, sa.Column(name, sa.Integer(), nullable=False, server_default="1"))
        for name in ("total_quantity", "available_quantity")
        if not has_column("keys", name)
    ]
    if added:
        with op.batch_alter_table("keys") as batch_op:
            for _, column in added:
                batch_op.add_column(column)

    op.execute(
        """
        UPDATE keys
        SET available_quantity = CASE
            WHEN (
                SELECT COUNT(1)
                FROM key_assignments
                WHERE key_assignments.key_id = keys.id
                  AND key_assignments.returned_at IS NULL
            ) >= total_quantity THEN 0
            ELSE total_quantity - (
                SELECT COUNT(1)
                FROM key_assignments
                WHERE key_assignments.key_id = keys.id
                  AND key_assignments.returned_at IS NULL
            )
        END
        """
    )

    checks = [
        ("ck_keys_total_quantity_positive", "total_quantity >= 1"),
        ("ck_keys_available_quantity_non_negative", "available_quantity >= 0"),
        ("ck_keys_available_lte_total", "available_quantity <= total_quantity"),
    ]
    missing_checks = [(name, expr) for name, expr in checks if not has_constraint("keys", name, "check")]
    if added or missing_checks:
        with op.batch_alter_table("keys") as batch_op:
            if added:
                batch_op.alter_column("total_quantity", server_default=None)
                batch_op.alter_column("available_quantity", server_default=None)
            for name, expr in missing_checks:
                batch_op.create_check_constraint(name, expr)

    # Dropped from the model, so create_all never emits it on a fresh database.
    if has_constraint("key_assignments", "uq_key_returned_state", "unique"):
        with op.batch_alter_table("key_assignments") as batch_op:
            batch_op.drop_constraint("uq_key_returned_state", type_="unique")


def downgrade() -> None:
    with op.batch_alter_table("key_assignments") as batch_op:
        batch_op.create_unique_constraint("uq_key_returned_state", ["key_id", "returned_at"])

    with op.batch_alter_table("keys") as batch_op:
        batch_op.drop_constraint("ck_keys_available_lte_total", type_="check")
        batch_op.drop_constraint("ck_keys_available_quantity_non_negative", type_="check")
        batch_op.drop_constraint("ck_keys_total_quantity_positive", type_="check")
        batch_op.drop_column("available_quantity")
        batch_op.drop_column("total_quantity")
