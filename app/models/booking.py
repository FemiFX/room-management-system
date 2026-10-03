from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.enums import BookingSource, BookingStatus
from app.models.mixins import TimestampMixin


class Booking(TimestampMixin, Base):
    __tablename__ = "bookings"

    id: Mapped[int] = mapped_column(primary_key=True)
    room_id: Mapped[int] = mapped_column(ForeignKey("rooms.id"), nullable=False, index=True)
    party_id: Mapped[int] = mapped_column(ForeignKey("parties.id"), nullable=False, index=True)

    title: Mapped[str] = mapped_column(String(255), nullable=False)
    start_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    end_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    status: Mapped[BookingStatus] = mapped_column(
        Enum(BookingStatus, native_enum=False, values_callable=lambda x: [e.value for e in x]),
        default=BookingStatus.PENDING,
        nullable=False,
        index=True,
    )

    #: Which front door this booking came through. On `bookings` rather than
    #: the request envelope because the admin list renders it per row.
    source: Mapped[BookingSource] = mapped_column(
        Enum(BookingSource, native_enum=False, values_callable=lambda x: [e.value for e in x]),
        default=BookingSource.STAFF,
        nullable=False,
        index=True,
    )
    #: The signed-in user who made it. NULL for public requests, which have no
    #: user -- their requester details live on the BookingRequest envelope.
    created_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), index=True)

    purpose: Mapped[str | None] = mapped_column(String(255))
    attendee_count: Mapped[int | None] = mapped_column(Integer)
    notes: Mapped[str | None] = mapped_column(Text)

    room: Mapped["Room"] = relationship(back_populates="bookings")
    party: Mapped["Party"] = relationship(back_populates="bookings")
    created_by: Mapped["User | None"] = relationship(back_populates="bookings_created")
    request: Mapped["BookingRequest | None"] = relationship(
        back_populates="booking",
        cascade="all, delete-orphan",
        uselist=False,
    )
    equipment_requests: Mapped[list["BookingEquipmentRequest"]] = relationship(
        back_populates="booking",
        cascade="all, delete-orphan",
    )
    service_requests: Mapped[list["BookingServiceRequest"]] = relationship(
        back_populates="booking",
        cascade="all, delete-orphan",
    )
    #: Deliberately NOT delete-orphan: a document is a file in object storage
    #: as well as a row, and deleting a booking should not silently bin it.
    documents: Mapped[list["Document"]] = relationship(back_populates="booking")


