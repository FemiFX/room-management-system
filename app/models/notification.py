from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import JSON, DateTime, Enum, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.enums import NotificationStatus
from app.models.mixins import TimestampMixin


class Notification(TimestampMixin, Base):
    __tablename__ = "notifications"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    link: Mapped[str | None] = mapped_column(String(512))
    status: Mapped[NotificationStatus] = mapped_column(
        Enum(NotificationStatus, native_enum=False, values_callable=lambda x: [e.value for e in x]),
        default=NotificationStatus.UNREAD,
        nullable=False,
        index=True,
    )
    details_json: Mapped[dict | None] = mapped_column(JSON)
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    user: Mapped["User"] = relationship(back_populates="notifications")

    @property
    def time_ago(self) -> str:
        now = datetime.now(timezone.utc)
        diff = now - self.created_at
        if diff.days > 0:
            return f"{diff.days}d"
        hours = diff.seconds // 3600
        if hours > 0:
            return f"{hours}h"
        minutes = diff.seconds // 60
        if minutes > 0:
            return f"{minutes}m"
        return "now"

