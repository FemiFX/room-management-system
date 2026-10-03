"""listing thumbnails for buildings and rooms

Revision ID: 20260904_0018
Revises: 20260903_0017
Create Date: 2026-09-04

Adds the nullable image_object_key that `floors` has had all along, so the
building and room listings can show a photo. Nullable on purpose: every
existing row keeps working and the card falls back to a tinted initial.
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

from app.db.migration_helpers import has_column

revision = "20260904_0018"
down_revision = "20260903_0017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Guarded: 0001 runs create_all, so these columns exist on a fresh database.
    if not has_column("buildings", "image_object_key"):
        op.add_column("buildings", sa.Column("image_object_key", sa.String(length=255), nullable=True))
    if not has_column("rooms", "image_object_key"):
        op.add_column("rooms", sa.Column("image_object_key", sa.String(length=255), nullable=True))


def downgrade() -> None:
    if has_column("rooms", "image_object_key"):
        op.drop_column("rooms", "image_object_key")
    if has_column("buildings", "image_object_key"):
        op.drop_column("buildings", "image_object_key")
