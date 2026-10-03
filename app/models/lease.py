from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import Date, Enum, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.enums import LeaseStatus
from app.models.mixins import TimestampMixin


class Lease(TimestampMixin, Base):
    __tablename__ = "leases"

    id: Mapped[int] = mapped_column(primary_key=True)
    room_id: Mapped[int] = mapped_column(ForeignKey("rooms.id"), nullable=False, index=True)
    party_id: Mapped[int] = mapped_column(ForeignKey("parties.id"), nullable=False, index=True)

    contract_reference: Mapped[str | None] = mapped_column(String(100), unique=True)
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date | None] = mapped_column(Date)
    notice_period_days: Mapped[int | None] = mapped_column(Integer)

    monthly_rent: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    deposit_amount: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    currency: Mapped[str] = mapped_column(String(3), default="EUR", nullable=False)

    status: Mapped[LeaseStatus] = mapped_column(
        Enum(LeaseStatus, native_enum=False, values_callable=lambda x: [e.value for e in x]),
        default=LeaseStatus.DRAFT,
        nullable=False,
        index=True,
    )

    notes: Mapped[str | None] = mapped_column(Text)

    room: Mapped["Room"] = relationship(back_populates="leases")
    party: Mapped["Party"] = relationship(back_populates="leases")
    documents: Mapped[list["Document"]] = relationship(back_populates="lease")


