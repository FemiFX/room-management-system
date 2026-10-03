from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Index, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.enums import Role
from app.models.mixins import TimestampMixin


class User(TimestampMixin, Base):
    __tablename__ = "users"
    # Partial uniqueness: many users legitimately have no party and no
    # Nextcloud account, so a plain UNIQUE would collide on NULL under some
    # dialects. Mirrors the pattern in InternalRoomAssignment.
    __table_args__ = (
        Index(
            "uq_users_party_id",
            "party_id",
            unique=True,
            postgresql_where=text("party_id IS NOT NULL"),
            sqlite_where=text("party_id IS NOT NULL"),
        ),
        Index(
            "uq_users_nc_user_id",
            "nc_user_id",
            unique=True,
            postgresql_where=text("nc_user_id IS NOT NULL"),
            sqlite_where=text("nc_user_id IS NOT NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[Role] = mapped_column(
        Enum(Role, native_enum=False, values_callable=lambda x: [e.value for e in x]),
        default=Role.VIEWER,
        nullable=False,
    )
    preferred_language: Mapped[str] = mapped_column(String(8), nullable=False, default="de")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    oidc_subject: Mapped[str | None] = mapped_column(String(255), unique=True, index=True)
    oidc_issuer: Mapped[str | None] = mapped_column(String(255))
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    groups_json: Mapped[str | None] = mapped_column(Text)

    #: Bridge to the contact record. Set by the Nextcloud sync for members, so a
    #: member's booking can carry a party_id. Unique when set.
    party_id: Mapped[int | None] = mapped_column(ForeignKey("parties.id"))
    #: Nextcloud uid. A second login key alongside email, so an address change
    #: upstream does not lock the account out. Unique when set.
    nc_user_id: Mapped[str | None] = mapped_column(String(255))

    audit_entries: Mapped[list["AuditLog"]] = relationship(back_populates="actor", cascade="all, delete-orphan")
    notifications: Mapped[list["Notification"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    internal_room_assignments_assigned: Mapped[list["InternalRoomAssignment"]] = relationship(back_populates="assigned_by")
    party: Mapped["Party | None"] = relationship(back_populates="users")
    bookings_created: Mapped[list["Booking"]] = relationship(back_populates="created_by")
