from __future__ import annotations

from sqlalchemy import ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.mixins import TimestampMixin


class RoomService(TimestampMixin, Base):
    """Which extra services a given room offers.

    Services used to be global: every active service appeared on the public
    form whichever room was picked, which is wrong for a technician who only
    covers the hall. Equipment was already per-room (`room_equipment`); this
    is the same shape for services.

    A row means "offered". Absence means "not offered" -- so the migration
    that creates this table backfills a row for every active service on every
    active room, which reproduces the old behaviour exactly.
    """

    __tablename__ = "room_services"
    __table_args__ = (UniqueConstraint("room_id", "service_id", name="uq_room_service"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    room_id: Mapped[int] = mapped_column(
        ForeignKey("rooms.id", ondelete="CASCADE"), nullable=False, index=True
    )
    service_id: Mapped[int] = mapped_column(
        ForeignKey("booking_services.id", ondelete="CASCADE"), nullable=False, index=True
    )

    room: Mapped["Room"] = relationship(back_populates="service_links")
    service: Mapped["BookingService"] = relationship(back_populates="room_links")
