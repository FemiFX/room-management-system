from __future__ import annotations

from sqlalchemy import ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.mixins import TimestampMixin


class Floor(TimestampMixin, Base):
    __tablename__ = "floors"

    id: Mapped[int] = mapped_column(primary_key=True)
    building_id: Mapped[int] = mapped_column(ForeignKey("buildings.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    floor_number: Mapped[int] = mapped_column(Integer, nullable=False)
    floorplan_object_key: Mapped[str | None] = mapped_column(String(255))
    image_object_key: Mapped[str | None] = mapped_column(String(255))
    notes: Mapped[str | None] = mapped_column(Text)

    building: Mapped["Building"] = relationship(back_populates="floors")
    rooms: Mapped[list["Room"]] = relationship(back_populates="floor", cascade="all, delete-orphan")


