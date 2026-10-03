from __future__ import annotations

from datetime import date

from sqlalchemy import Date, ForeignKey, Index, Text, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.mixins import TimestampMixin


class InternalRoomAssignment(TimestampMixin, Base):
    __tablename__ = "internal_room_assignments"
    __table_args__ = (
        Index(
            "uq_internal_room_assignments_active_room",
            "room_id",
            unique=True,
            postgresql_where=text("end_date IS NULL"),
            sqlite_where=text("end_date IS NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    room_id: Mapped[int] = mapped_column(ForeignKey("rooms.id"), nullable=False, index=True)
    party_id: Mapped[int] = mapped_column(ForeignKey("parties.id"), nullable=False, index=True)
    assigned_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), index=True)

    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date | None] = mapped_column(Date)
    notes: Mapped[str | None] = mapped_column(Text)

    room: Mapped["Room"] = relationship(back_populates="internal_assignments")
    party: Mapped["Party"] = relationship(back_populates="internal_room_assignments")
    assigned_by: Mapped["User | None"] = relationship(back_populates="internal_room_assignments_assigned")
