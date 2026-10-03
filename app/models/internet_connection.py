from __future__ import annotations

from sqlalchemy import Boolean, Enum, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.enums import InternetMedium
from app.models.mixins import TimestampMixin


class InternetConnection(TimestampMixin, Base):
    __tablename__ = "internet_connections"

    id: Mapped[int] = mapped_column(primary_key=True)
    room_id: Mapped[int] = mapped_column(ForeignKey("rooms.id"), nullable=False, index=True)

    medium: Mapped[InternetMedium] = mapped_column(
        Enum(InternetMedium, native_enum=False, values_callable=lambda x: [e.value for e in x]),
        nullable=False,
    )
    channel: Mapped[str | None] = mapped_column(String(100))
    provider: Mapped[str | None] = mapped_column(String(100))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text)

    room: Mapped["Room"] = relationship(back_populates="internet_connections")


