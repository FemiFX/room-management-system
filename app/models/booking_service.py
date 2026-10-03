from __future__ import annotations

from sqlalchemy import Boolean, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.mixins import TimestampMixin


class BookingService(TimestampMixin, Base):
    """Extra services a booking can request -- technician, usher, and so on.

    A table rather than a hardcoded list, so the catalogue can be edited
    without a deploy. No price column: billing is deliberately not a finance
    surface here, and adding one later is purely additive.
    """

    __tablename__ = "booking_services"

    id: Mapped[int] = mapped_column(primary_key=True)
    #: Stable machine key. The display `name` is free to change; this is not.
    code: Mapped[str] = mapped_column(String(50), nullable=False, unique=True, index=True)
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    booking_links: Mapped[list["BookingServiceRequest"]] = relationship(
        back_populates="service",
        cascade="all, delete-orphan",
    )
    room_links: Mapped[list["RoomService"]] = relationship(
        back_populates="service",
        cascade="all, delete-orphan",
    )
