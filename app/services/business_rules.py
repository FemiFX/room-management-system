from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from app.models.booking import Booking
from app.models.enums import BookingStatus, LeaseStatus, OccupancyMode, PartyType
from app.models.internal_room_assignment import InternalRoomAssignment
from app.models.key import KeyAssignment
from app.models.lease import Lease
from app.models.party import Party
from app.models.room import Room
from app.core.time_utils import app_now


def ranges_overlap(start1, end1, start2, end2) -> bool:
    end1_value = end1 or datetime.max.date() if isinstance(start1, date) else end1 or datetime.max
    end2_value = end2 or datetime.max.date() if isinstance(start2, date) else end2 or datetime.max
    return start1 <= end2_value and start2 <= end1_value


def validate_room_can_have_lease(room: Room) -> None:
    if room.occupancy_mode == OccupancyMode.INTERNAL:
        raise ValueError("Internal rooms cannot have leases.")


def ensure_no_active_lease_overlap(
    db: Session,
    *,
    room_id: int,
    start_date: date,
    end_date: date | None,
    exclude_lease_id: int | None = None,
) -> None:
    stmt = select(Lease).where(
        Lease.room_id == room_id,
        Lease.status == LeaseStatus.ACTIVE,
    )
    if exclude_lease_id is not None:
        stmt = stmt.where(Lease.id != exclude_lease_id)
    candidates = db.scalars(stmt).all()
    for lease in candidates:
        if ranges_overlap(start_date, end_date, lease.start_date, lease.end_date):
            raise ValueError("Overlapping active lease exists for this room.")


def ensure_booking_approval_allowed(
    db: Session,
    *,
    room_id: int,
    start_at: datetime,
    end_at: datetime,
    exclude_booking_id: int | None = None,
) -> None:
    """Thin wrapper kept for existing callers; the rules live in services.bookings.

    Note this now uses half-open comparison, matching `scan_booking_conflicts`
    in app/jobs/tasks.py. Those two disagreed before: the nightly scan used
    half-open while this gate used `ranges_overlap`, which is inclusive, so a
    pair of touching bookings was refused at approval and then not reported as
    a conflict afterwards.

    `ranges_overlap` itself is unchanged -- its other callers compare dates,
    where an inclusive end really is inclusive.
    """
    from app.services.bookings import ensure_available

    try:
        ensure_available(
            db,
            room_id=room_id,
            start_at=start_at,
            end_at=end_at,
            exclude_booking_id=exclude_booking_id,
        )
    except Exception as exc:  # RoomUnavailable and friends are ValueErrors
        raise ValueError(str(exc)) from exc


def ensure_active_party(db: Session, *, party_id: int) -> Party:
    party = db.get(Party, party_id)
    if party is None or not party.is_active:
        raise ValueError("Key assignment requires an active party.")
    return party


def validate_room_can_have_internal_assignment(room: Room) -> None:
    if room.occupancy_mode not in {OccupancyMode.INTERNAL, OccupancyMode.MIXED}:
        raise ValueError("Internal assignments are allowed only for internal or mixed rooms.")


def ensure_team_party_for_internal_assignment(db: Session, *, party_id: int) -> Party:
    party = db.get(Party, party_id)
    if party is None:
        raise ValueError("Party not found.")
    if not party.is_active:
        raise ValueError("Internal assignment requires an active team.")
    if party.party_type != PartyType.TEAM:
        raise ValueError("Internal assignment requires a team party.")
    return party


def ensure_no_active_internal_assignment_overlap(
    db: Session,
    *,
    room_id: int,
    start_date: date,
    end_date: date | None,
    exclude_assignment_id: int | None = None,
) -> None:
    stmt = select(InternalRoomAssignment).where(
        InternalRoomAssignment.room_id == room_id,
        InternalRoomAssignment.end_date.is_(None),
    )
    if exclude_assignment_id is not None:
        stmt = stmt.where(InternalRoomAssignment.id != exclude_assignment_id)
    active_assignment = db.scalar(stmt)
    if active_assignment is not None and ranges_overlap(
        start_date, end_date, active_assignment.start_date, active_assignment.end_date
    ):
        raise ValueError("An active internal assignment already exists for this room.")


def active_internal_assignment_for_room(
    db: Session, room_id: int, today: date | None = None
) -> InternalRoomAssignment | None:
    if today is None:
        today = date.today()
    stmt = (
        select(InternalRoomAssignment)
        .where(
            InternalRoomAssignment.room_id == room_id,
            InternalRoomAssignment.start_date <= today,
            or_(
                InternalRoomAssignment.end_date.is_(None),
                InternalRoomAssignment.end_date >= today,
            ),
        )
        .order_by(InternalRoomAssignment.start_date.desc())
    )
    return db.scalar(stmt)


def active_lease_for_room(db: Session, room_id: int, today: date | None = None) -> Lease | None:
    if today is None:
        today = date.today()
    stmt = (
        select(Lease)
        .where(
            Lease.room_id == room_id,
            Lease.status == LeaseStatus.ACTIVE,
            Lease.start_date <= today,
            or_(Lease.end_date.is_(None), Lease.end_date >= today),
        )
        .order_by(Lease.start_date.desc())
    )
    return db.scalar(stmt)


def current_approved_booking_for_room(db: Session, room_id: int, now: datetime | None = None) -> Booking | None:
    if now is None:
        now = app_now()
    stmt = select(Booking).where(
        Booking.room_id == room_id,
        Booking.status == BookingStatus.APPROVED,
        Booking.start_at <= now,
        Booking.end_at >= now,
    )
    return db.scalar(stmt)


def next_approved_booking_for_room(db: Session, room_id: int, now: datetime | None = None) -> Booking | None:
    if now is None:
        now = app_now()
    stmt = (
        select(Booking)
        .where(
            Booking.room_id == room_id,
            Booking.status == BookingStatus.APPROVED,
            Booking.start_at > now,
        )
        .order_by(Booking.start_at.asc())
    )
    return db.scalar(stmt)


def active_key_assignments_for_room(db: Session, room_id: int) -> list[KeyAssignment]:
    stmt = select(KeyAssignment).where(
        KeyAssignment.room_id == room_id,
        KeyAssignment.returned_at.is_(None),
    )
    return list(db.scalars(stmt).all())


def key_assignments_requiring_recovery(db: Session, *, today: date | None = None) -> list[KeyAssignment]:
    if today is None:
        today = date.today()

    assignments = list(
        db.scalars(
            select(KeyAssignment)
            .where(KeyAssignment.returned_at.is_(None))
        ).all()
    )
    if not assignments:
        return []

    party_ids = {assignment.party_id for assignment in assignments}
    room_ids = {assignment.room_id for assignment in assignments}
    leases = list(
        db.scalars(
            select(Lease).where(
                Lease.party_id.in_(party_ids),
                Lease.room_id.in_(room_ids),
            )
        ).all()
    )
    lease_map: dict[tuple[int, int], list[Lease]] = {}
    for lease in leases:
        lease_map.setdefault((lease.party_id, lease.room_id), []).append(lease)

    recoveries: list[KeyAssignment] = []
    for assignment in assignments:
        party = assignment.party
        if party and party.party_type == PartyType.PERSON and party.nc_user_id and not party.is_active:
            setattr(assignment, "recovery_reason", "inactive_person")
            recoveries.append(assignment)
            continue

        pair_leases = lease_map.get((assignment.party_id, assignment.room_id), [])
        if not pair_leases:
            continue
        has_active_lease = any(
            lease.status == LeaseStatus.ACTIVE
            and lease.start_date <= today
            and (lease.end_date is None or lease.end_date >= today)
            for lease in pair_leases
        )
        if has_active_lease:
            continue

        has_expired_or_ended = any(
            (lease.end_date is not None and lease.end_date < today)
            or lease.status in {LeaseStatus.EXPIRED, LeaseStatus.TERMINATED, LeaseStatus.CANCELLED}
            for lease in pair_leases
        )
        if has_expired_or_ended:
            setattr(assignment, "recovery_reason", "lease_expired")
            recoveries.append(assignment)

    return recoveries


def compute_room_status(db: Session, room: Room) -> str:
    if not room.is_active:
        return "unavailable"

    now_booking = current_approved_booking_for_room(db, room.id)
    if now_booking is not None:
        return "booked_now"

    internal_assignment = active_internal_assignment_for_room(db, room.id)
    if internal_assignment is not None:
        return "occupied"

    lease = active_lease_for_room(db, room.id)
    if lease is not None:
        return "occupied"

    next_booking = next_approved_booking_for_room(db, room.id)
    if next_booking is not None:
        return "available_until_booking"

    return "available"
