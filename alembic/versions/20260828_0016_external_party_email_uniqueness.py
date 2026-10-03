"""enforce one external party per email

Revision ID: 20260828_0016
Revises: 20260828_0015
Create Date: 2026-08-28
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

from app.db.migration_helpers import has_index

revision = "20260828_0016"
down_revision = "20260828_0015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Makes public find-or-create race-proof rather than best-effort: two
    # concurrent submissions from the same address cannot create two parties.
    #
    # Safe by construction -- PartyType.EXTERNAL is new in this release, so no
    # existing row can violate it. Scoped to external parties only; staff and
    # tenant records legitimately share or omit addresses.
    if not has_index("parties", "uq_parties_external_email"):
        op.create_index(
            "uq_parties_external_email",
            "parties",
            [sa.text("lower(email)")],
            unique=True,
            postgresql_where=sa.text("party_type = 'external' AND email IS NOT NULL"),
            sqlite_where=sa.text("party_type = 'external' AND email IS NOT NULL"),
        )


def downgrade() -> None:
    op.drop_index("uq_parties_external_email", table_name="parties")
