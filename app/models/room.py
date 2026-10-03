from __future__ import annotations

from decimal import Decimal

from sqlalchemy import Boolean, Enum, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.enums import OccupancyMode
from app.models.mixins import TimestampMixin


class Room(TimestampMixin, Base):
    __tablename__ = "rooms"

    id: Mapped[int] = mapped_column(primary_key=True)
    floor_id: Mapped[int] = mapped_column(ForeignKey("floors.id"), nullable=False, index=True)
    room_code: Mapped[str] = mapped_column(String(50), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(150), nullable=False)

    length_m: Mapped[Decimal | None] = mapped_column(Numeric(8, 2))
    width_m: Mapped[Decimal | None] = mapped_column(Numeric(8, 2))
    height_m: Mapped[Decimal | None] = mapped_column(Numeric(8, 2))
    area_sqm: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))

    usage_type: Mapped[str] = mapped_column(String(50), nullable=False)
    occupancy_mode: Mapped[OccupancyMode] = mapped_column(
        Enum(OccupancyMode, native_enum=False, values_callable=lambda x: [e.value for e in x]),
        default=OccupancyMode.LEASABLE,
        nullable=False,
    )

    rentable: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    #: Bookable by staff and by signed-in members (the internal audience).
    bookable: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    #: Offered on the public booking form. Independent of `bookable`: a room may
    #: be public-only, internal-only, both, or neither.
    public_bookable: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    #: Seats. Checked against a booking's attendee_count when both are set.
    capacity: Mapped[int | None] = mapped_column(Integer)
    #: Shown on the public form; the internal `notes` are not public.
    public_description: Mapped[str | None] = mapped_column(Text)
    #: Object key of the listing thumbnail, same storage as documents.
    image_object_key: Mapped[str | None] = mapped_column(String(255))
    #: Per-day cleaning rate. NULL means no charge applies to this room.
    cleaning_rate_daily: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))

    meter_number: Mapped[str | None] = mapped_column(String(100))
    has_internet: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    floor: Mapped["Floor"] = relationship(back_populates="rooms")
    keys: Mapped[list["Key"]] = relationship(back_populates="room")
    internal_assignments: Mapped[list["InternalRoomAssignment"]] = relationship(
        back_populates="room",
        cascade="all, delete-orphan",
    )
    leases: Mapped[list["Lease"]] = relationship(back_populates="room", cascade="all, delete-orphan")
    bookings: Mapped[list["Booking"]] = relationship(back_populates="room", cascade="all, delete-orphan")
    key_assignments: Mapped[list["KeyAssignment"]] = relationship(back_populates="room", cascade="all, delete-orphan")
    room_equipment: Mapped[list["RoomEquipment"]] = relationship(back_populates="room", cascade="all, delete-orphan")
    service_links: Mapped[list["RoomService"]] = relationship(back_populates="room", cascade="all, delete-orphan")
    internet_connections: Mapped[list["InternetConnection"]] = relationship(back_populates="room", cascade="all, delete-orphan")
    documents: Mapped[list["Document"]] = relationship(back_populates="room", cascade="all, delete-orphan")
