from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.models.booking import Booking
from app.models.enums import BookingStatus, LeaseStatus
from app.models.key import KeyAssignment
from app.models.lease import Lease
from app.models.room import Room
from app.services.business_rules import key_assignments_requiring_recovery
from app.core.time_utils import app_now


def dashboard_summary(db: Session) -> dict[str, int]:
    today = date.today()
    now = app_now()

    total_rooms = db.scalar(select(func.count(Room.id))) or 0
    active_rooms = db.scalar(select(func.count(Room.id)).where(Room.is_active.is_(True))) or 0

    occupied_rooms = db.scalar(
        select(func.count(func.distinct(Lease.room_id))).where(
            Lease.status == LeaseStatus.ACTIVE,
            Lease.start_date <= today,
            or_(Lease.end_date.is_(None), Lease.end_date >= today),
        )
    ) or 0

    rooms_booked_today = db.scalar(
        select(func.count(func.distinct(Booking.room_id))).where(
            Booking.status == BookingStatus.APPROVED,
            Booking.start_at <= now,
            Booking.end_at >= now,
        )
    ) or 0

    expiring_leases_30d = db.scalar(
        select(func.count(Lease.id)).where(
            Lease.status == LeaseStatus.ACTIVE,
            Lease.end_date.is_not(None),
            Lease.end_date <= today + timedelta(days=30),
            Lease.end_date >= today,
        )
    ) or 0

    unreturned_keys = db.scalar(select(func.count(KeyAssignment.id)).where(KeyAssignment.returned_at.is_(None))) or 0

    return {
        "total_rooms": int(total_rooms),
        "active_rooms": int(active_rooms),
        "occupied_rooms": int(occupied_rooms),
        "rooms_booked_now": int(rooms_booked_today),
        "expiring_leases_30d": int(expiring_leases_30d),
        "unreturned_keys": int(unreturned_keys),
    }


def action_center_items(db: Session) -> list[dict[str, str | int]]:
    summary = dashboard_summary(db)
    items: list[dict[str, str | int]] = []
    recoveries_needed = len(key_assignments_requiring_recovery(db))

    if summary["expiring_leases_30d"]:
        items.append(
            {
                "code": "leases_expiring",
                "severity": "warning",
                "count": summary["expiring_leases_30d"],
                "message": "Leases expiring within 30 days",
            }
        )

    if recoveries_needed:
        items.append(
            {
                "code": "keys_recovery",
                "severity": "error",
                "count": int(recoveries_needed),
                "message": "Inactive synced persons still hold keys",
            }
        )

    return items
