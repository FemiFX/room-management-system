from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.enums import DocumentType
from app.models.mixins import TimestampMixin


class Document(TimestampMixin, Base):
    __tablename__ = "documents"

    id: Mapped[int] = mapped_column(primary_key=True)
    room_id: Mapped[int | None] = mapped_column(ForeignKey("rooms.id"), index=True)
    lease_id: Mapped[int | None] = mapped_column(ForeignKey("leases.id"), index=True)
    #: A document can hang off a booking the same way it hangs off a room or
    #: a lease -- an insurance certificate belongs to the booking it covers.
    booking_id: Mapped[int | None] = mapped_column(ForeignKey("bookings.id"), index=True)
    uploaded_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), index=True)

    document_type: Mapped[DocumentType] = mapped_column(
        Enum(DocumentType, native_enum=False, values_callable=lambda x: [e.value for e in x]),
        nullable=False,
        index=True,
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    object_key: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    original_filename: Mapped[str | None] = mapped_column(String(255))
    mime_type: Mapped[str | None] = mapped_column(String(120))
    file_size: Mapped[int | None] = mapped_column(Integer)
    uploaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    notes: Mapped[str | None] = mapped_column(Text)

    room: Mapped["Room | None"] = relationship(back_populates="documents")
    lease: Mapped["Lease | None"] = relationship(back_populates="documents")
    booking: Mapped["Booking | None"] = relationship(back_populates="documents")
    uploaded_by: Mapped["User | None"] = relationship("User")

