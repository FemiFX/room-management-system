from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.mixins import TimestampMixin


class Key(TimestampMixin, Base):
    __tablename__ = "keys"
    __table_args__ = (
        CheckConstraint("total_quantity >= 1", name="ck_keys_total_quantity_positive"),
        CheckConstraint("available_quantity >= 0", name="ck_keys_available_quantity_non_negative"),
        CheckConstraint("available_quantity <= total_quantity", name="ck_keys_available_lte_total"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    room_id: Mapped[int | None] = mapped_column(ForeignKey("rooms.id", ondelete="SET NULL"), index=True)
    key_code: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    description: Mapped[str | None] = mapped_column(String(255))
    hanging_location: Mapped[str | None] = mapped_column(String(120))
    master_key: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    total_quantity: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    available_quantity: Mapped[int] = mapped_column(Integer, default=1, nullable=False)

    room: Mapped["Room | None"] = relationship(back_populates="keys")
    assignments: Mapped[list["KeyAssignment"]] = relationship(back_populates="key", cascade="all, delete-orphan")


class KeyAssignment(TimestampMixin, Base):
    __tablename__ = "key_assignments"

    id: Mapped[int] = mapped_column(primary_key=True)
    key_id: Mapped[int] = mapped_column(ForeignKey("keys.id"), nullable=False, index=True)
    room_id: Mapped[int] = mapped_column(ForeignKey("rooms.id"), nullable=False, index=True)
    party_id: Mapped[int] = mapped_column(ForeignKey("parties.id"), nullable=False, index=True)

    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    returned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    issue_note: Mapped[str | None] = mapped_column(Text)
    issue_receipt_object_key: Mapped[str | None] = mapped_column(String(255))
    issue_receipt_filename: Mapped[str | None] = mapped_column(String(255))
    issue_receipt_mime_type: Mapped[str | None] = mapped_column(String(120))
    issue_receipt_size: Mapped[int | None] = mapped_column(Integer)
    return_note: Mapped[str | None] = mapped_column(Text)

    key: Mapped["Key"] = relationship(back_populates="assignments")
    room: Mapped["Room"] = relationship(back_populates="key_assignments")
    party: Mapped["Party"] = relationship(back_populates="key_assignments")
