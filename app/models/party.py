from __future__ import annotations

from sqlalchemy import Boolean, Enum, Index, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.enums import PartyType
from app.models.mixins import TimestampMixin


class Party(TimestampMixin, Base):
    __tablename__ = "parties"
    # One external party per email address, so public find-or-create is
    # race-proof. Scoped to EXTERNAL: staff and tenant records legitimately
    # share or omit an address.
    __table_args__ = (
        Index(
            "uq_parties_external_email",
            text("lower(email)"),
            unique=True,
            postgresql_where=text("party_type = 'external' AND email IS NOT NULL"),
            sqlite_where=text("party_type = 'external' AND email IS NOT NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    nc_user_id: Mapped[str | None] = mapped_column(String(255), unique=True, index=True)
    party_type: Mapped[PartyType] = mapped_column(
        Enum(PartyType, native_enum=False, values_callable=lambda x: [e.value for e in x]),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    email: Mapped[str | None] = mapped_column(String(255))
    phone: Mapped[str | None] = mapped_column(String(100))
    street: Mapped[str | None] = mapped_column(String(255))
    postal_code: Mapped[str | None] = mapped_column(String(20))
    city: Mapped[str | None] = mapped_column(String(120))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text)

    leases: Mapped[list["Lease"]] = relationship(back_populates="party")
    bookings: Mapped[list["Booking"]] = relationship(back_populates="party")
    key_assignments: Mapped[list["KeyAssignment"]] = relationship(back_populates="party")
    internal_room_assignments: Mapped[list["InternalRoomAssignment"]] = relationship(back_populates="party")
    users: Mapped[list["User"]] = relationship(back_populates="party")
