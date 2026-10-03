"""The request envelope around a Booking.

The public form collects considerably more than the core `Booking` model can
hold -- requester identity, billing details, a cleaning quote, a public
reference. Rather than widen `bookings` with columns only one audience uses,
this keeps them in a 1:1 side table.

The requester fields are a deliberate *snapshot*, not a view onto the Party.
They record what was actually submitted, and stay accurate even if the Party
row is later edited or merged.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.mixins import TimestampMixin


class BookingRequest(TimestampMixin, Base):
    __tablename__ = "booking_requests"

    id: Mapped[int] = mapped_column(primary_key=True)
    booking_id: Mapped[int] = mapped_column(
        ForeignKey("bookings.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )

    #: Customer-quotable reference. Never an authorisation credential on its
    #: own -- managing a booking needs the signed token, not this.
    public_ref: Mapped[str] = mapped_column(String(24), nullable=False, unique=True, index=True)
    #: Bumped to revoke outstanding manage links (on cancel, or staff rejection).
    token_version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    #: The language the request was made in. Persisted because emails are sent
    #: from a Celery worker, which has no request to resolve a language from.
    language: Mapped[str] = mapped_column(String(8), nullable=False, default="de")

    # --- requester snapshot (NULL for internal and staff bookings) ---
    requester_first_name: Mapped[str | None] = mapped_column(String(150))
    requester_last_name: Mapped[str | None] = mapped_column(String(150))
    requester_academic_title: Mapped[str | None] = mapped_column(String(100))
    requester_organization: Mapped[str | None] = mapped_column(String(255))
    requester_email: Mapped[str | None] = mapped_column(String(255), index=True)
    requester_phone: Mapped[str | None] = mapped_column(String(100))
    requester_address: Mapped[str | None] = mapped_column(Text)
    contact_person: Mapped[str | None] = mapped_column(String(255))

    billing_info: Mapped[str | None] = mapped_column(Text)
    additional_info: Mapped[str | None] = mapped_column(Text)
    whole_day: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    #: Did the requester say they carry liability cover? Three states, and the
    #: third one matters: NULL means the question was never put to them, which
    #: is the truth for staff and portal bookings, and for every row that
    #: existed before the question did. False is an actual "no".
    liability_insurance: Mapped[bool | None] = mapped_column(Boolean)

    # --- cleaning charge, computed server-side and snapshotted ---
    #: The room's rate at the time of booking, so a later rate change does not
    #: silently rewrite what the customer was quoted.
    cleaning_rate_daily: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    cleaning_days: Mapped[int | None] = mapped_column(Integer)
    cleaning_charge: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="EUR")

    #: Staff's reason for rejecting, quoted back in the rejection email.
    staff_note: Mapped[str | None] = mapped_column(Text)
    #: HMAC of the submitting IP, not the IP itself -- enough to correlate
    #: abuse, not enough to identify a visitor.
    submitted_ip_hash: Mapped[str | None] = mapped_column(String(64))

    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    #: One of "customer", "staff", "member".
    cancelled_by: Mapped[str | None] = mapped_column(String(20))

    booking: Mapped["Booking"] = relationship(back_populates="request")

    @property
    def requester_display_name(self) -> str | None:
        parts = [self.requester_first_name, self.requester_last_name]
        name = " ".join(part for part in parts if part).strip()
        return name or self.requester_organization or None


class BookingEquipmentRequest(TimestampMixin, Base):
    """Equipment a booking asked for, with quantities.

    Replaces the reference app's "Name: Qty, Name: Qty" text column, which
    broke on any item name containing ": " and could not be queried at all.
    """

    __tablename__ = "booking_equipment_requests"
    __table_args__ = (UniqueConstraint("booking_id", "equipment_id", name="uq_booking_equipment_request"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    booking_id: Mapped[int] = mapped_column(
        ForeignKey("bookings.id", ondelete="CASCADE"), nullable=False, index=True
    )
    equipment_id: Mapped[int] = mapped_column(ForeignKey("equipment.id"), nullable=False, index=True)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    notes: Mapped[str | None] = mapped_column(Text)

    booking: Mapped["Booking"] = relationship(back_populates="equipment_requests")
    equipment: Mapped["Equipment"] = relationship()


class BookingServiceRequest(TimestampMixin, Base):
    __tablename__ = "booking_service_requests"
    __table_args__ = (UniqueConstraint("booking_id", "service_id", name="uq_booking_service_request"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    booking_id: Mapped[int] = mapped_column(
        ForeignKey("bookings.id", ondelete="CASCADE"), nullable=False, index=True
    )
    service_id: Mapped[int] = mapped_column(ForeignKey("booking_services.id"), nullable=False, index=True)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    booking: Mapped["Booking"] = relationship(back_populates="service_requests")
    service: Mapped["BookingService"] = relationship(back_populates="booking_links")
