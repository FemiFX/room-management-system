from __future__ import annotations

from sqlalchemy import Boolean, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.mixins import TimestampMixin


class Equipment(TimestampMixin, Base):
    __tablename__ = "equipment"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(150), nullable=False, unique=True)
    category: Mapped[str | None] = mapped_column(String(100))
    notes: Mapped[str | None] = mapped_column(Text)

    room_links: Mapped[list["RoomEquipment"]] = relationship(back_populates="equipment", cascade="all, delete-orphan")


class RoomEquipment(TimestampMixin, Base):
    __tablename__ = "room_equipment"
    __table_args__ = (UniqueConstraint("room_id", "equipment_id", name="uq_room_equipment"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    room_id: Mapped[int] = mapped_column(ForeignKey("rooms.id"), nullable=False, index=True)
    equipment_id: Mapped[int] = mapped_column(ForeignKey("equipment.id"), nullable=False, index=True)

    quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    fixed: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text)

    room: Mapped["Room"] = relationship(back_populates="room_equipment")
    equipment: Mapped["Equipment"] = relationship(back_populates="room_links")


