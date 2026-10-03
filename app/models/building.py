from __future__ import annotations

from sqlalchemy import String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.mixins import TimestampMixin


class Building(TimestampMixin, Base):
    __tablename__ = "buildings"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    street: Mapped[str | None] = mapped_column(String(255))
    postal_code: Mapped[str | None] = mapped_column(String(20))
    city: Mapped[str | None] = mapped_column(String(120))
    notes: Mapped[str | None] = mapped_column(Text)
    #: Object key of the listing thumbnail, same storage as documents.
    #: Mirrors Floor.image_object_key rather than inventing a scheme.
    image_object_key: Mapped[str | None] = mapped_column(String(255))

    floors: Mapped[list["Floor"]] = relationship(back_populates="building", cascade="all, delete-orphan")


