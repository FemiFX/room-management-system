"""The one place a booking is created, validated and conflict-checked.

Three front doors share this: staff creating a booking in the admin UI, a
member instant-booking through the portal, and an anonymous request through the
public form. They differ only in who the party is, which status the booking
starts in, and which rooms they are allowed to reach -- everything else,
including the rules that keep two people out of the same room, lives here.

No FastAPI imports: every function takes a Session first and is exercisable
from a unit test without HTTP.
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.time_utils import app_now, app_timezone, to_app_tz
from app.models.booking import Booking
from app.models.booking_request import BookingEquipmentRequest, BookingRequest, BookingServiceRequest
from app.models.booking_service import BookingService
from app.models.enums import (
    BookingSource,
    BookingStatus,
    LeaseStatus,
    OccupancyMode,
    PartyType,
)
from app.models.equipment import RoomEquipment
from app.models.internal_room_assignment import InternalRoomAssignment
from app.models.lease import Lease
from app.models.party import Party
from app.models.room import Room
from app.models.user import User
from app.services.audit import audit

#: Namespace for the advisory lock, so booking locks cannot collide with any
#: other advisory lock this application might take later.
_ADVISORY_LOCK_NAMESPACE = 0x524D5342  # "RMSB"

#: Crockford base32 -- no I, L, O or U, so a reference read aloud or copied by
#: hand cannot be confused between 1/I, 0/O.
_REF_ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
_REF_LENGTH = 8

MAX_BOOKING_DURATION_DAYS = 30


class BookingError(ValueError):
    """A booking could not be made. `code` lets callers map it to a status."""

    def __init__(self, message: str, *, code: str = "invalid_booking") -> None:
        super().__init__(message)
        self.code = code


class RoomUnavailable(BookingError):
    """The room is taken. Carries the clashing intervals so the UI can show them."""

    def __init__(self, message: str, *, conflicts: list[dict] | None = None) -> None:
        super().__init__(message, code="room_unavailable")
        self.conflicts = conflicts or []


# --------------------------------------------------------------------------
# Inputs
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class EquipmentLine:
    equipment_id: int
    quantity: int
    notes: str | None = None


@dataclass(frozen=True)
class ServiceLine:
    service_id: int
    quantity: int = 1


@dataclass(frozen=True)
class TimeframeInput:
    start_at: datetime
    end_at: datetime
    whole_day: bool = False


@dataclass(frozen=True)
class BookingInput:
    room_id: int
    title: str
    timeframe: TimeframeInput
    purpose: str | None = None
    attendee_count: int | None = None
    notes: str | None = None
    contact_person: str | None = None
    billing_info: str | None = None
    additional_info: str | None = None
    #: The public form's liability-cover answer. None means the question was
    #: not asked, which is what staff and portal bookings mean.
    liability_insurance: bool | None = None
    language: str = "de"
    equipment: list[EquipmentLine] = field(default_factory=list)
    services: list[ServiceLine] = field(default_factory=list)


@dataclass(frozen=True)
class PublicRequesterInput:
    email: str
    first_name: str | None = None
    last_name: str | None = None
    academic_title: str | None = None
    organization: str | None = None
    phone: str | None = None
    address: str | None = None


# --------------------------------------------------------------------------
# Timeframe and pricing
# --------------------------------------------------------------------------


def normalize_timeframe(timeframe: TimeframeInput) -> tuple[datetime, datetime]:
    """Return a half-open ``[start, end)`` interval in the app timezone.

    A whole-day booking runs from 00:00 on the first day to 00:00 on the day
    *after* the last -- not to 23:59:59. The reference app used 23:59:59, which
    both leaves a one-second hole and makes two consecutive whole-day bookings
    collide on the shared boundary.
    """
    start = to_app_tz(timeframe.start_at)
    end = to_app_tz(timeframe.end_at)

    if timeframe.whole_day:
        tz = app_timezone()
        start = datetime.combine(start.date(), datetime.min.time(), tzinfo=tz)
        end = datetime.combine(end.date() + timedelta(days=1), datetime.min.time(), tzinfo=tz)

    return start, end


def _local_days_touched(start: datetime, end: datetime) -> int:
    """Distinct local calendar dates a half-open interval touches, minimum 1.

    An interval ending exactly at midnight does not touch the following day --
    that is the point of half-open -- so a booking from Mon 00:00 to Tue 00:00
    is one day, not two.
    """
    start_date: date = start.date()
    end_date: date = end.date()
    if end.time() == datetime.min.time() and end_date > start_date:
        end_date -= timedelta(days=1)
    return max((end_date - start_date).days + 1, 1)


def compute_cleaning_charge(
    room: Room, start: datetime, end: datetime
) -> tuple[Decimal | None, int | None, Decimal | None]:
    """Return ``(rate, days, charge)``.

    Always computed here, never accepted from a client. The reference app
    computed this in the browser and wrote the posted value straight to the
    database, so the price was trivially forged.
    """
    rate = room.cleaning_rate_daily
    if rate is None:
        return None, None, None
    days = _local_days_touched(start, end)
    charge = (Decimal(rate) * days).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return Decimal(rate), days, charge


def generate_public_ref() -> str:
    return "RB-" + "".join(secrets.choice(_REF_ALPHABET) for _ in range(_REF_LENGTH))


# --------------------------------------------------------------------------
# Room eligibility
# --------------------------------------------------------------------------


def validate_room_for_source(room: Room, source: BookingSource) -> None:
    if not room.is_active:
        raise BookingError("Room is not available.", code="room_inactive")

    mixed = room.occupancy_mode == OccupancyMode.MIXED
    if source == BookingSource.PUBLIC:
        if not room.public_bookable:
            raise BookingError("Room is not publicly bookable.", code="room_not_public")
    elif source == BookingSource.INTERNAL:
        if not (room.bookable or mixed):
            raise BookingError("Room is not bookable.", code="room_not_bookable")
    else:  # STAFF -- may book anything a booking audience can reach.
        if not (room.bookable or room.public_bookable or mixed):
            raise BookingError("Room is not bookable.", code="room_not_bookable")


# --------------------------------------------------------------------------
# Conflicts
# --------------------------------------------------------------------------


def find_conflicts(
    db: Session,
    *,
    room_id: int,
    start_at: datetime,
    end_at: datetime,
    source: BookingSource = BookingSource.STAFF,
    exclude_booking_id: int | None = None,
) -> list[dict]:
    """Everything that stops this room being used for this interval.

    Half-open: 10:00-11:00 and 11:00-12:00 do not conflict. The reference app
    treated touching slots as a clash while missing genuine overnight overlaps
    entirely, because it compared date ranges and clock-time ranges as two
    separate one-dimensional overlaps.

    Only APPROVED bookings block. A PENDING public request is a request, not a
    reservation -- competing requests are allowed and staff choose between
    them.

    Leases and internal assignments block too. Without that, a member could
    instant-confirm a room let to a paying tenant: `compute_room_status`
    already treats those as occupied, but the booking rules never consulted
    them.
    """
    conflicts: list[dict] = []

    stmt = select(Booking).where(
        Booking.room_id == room_id,
        Booking.status == BookingStatus.APPROVED,
        Booking.start_at < end_at,
        Booking.end_at > start_at,
    )
    if exclude_booking_id is not None:
        stmt = stmt.where(Booking.id != exclude_booking_id)
    for row in db.scalars(stmt).all():
        conflicts.append(
            {
                "kind": "booking",
                "booking_id": row.id,
                "start_at": row.start_at,
                "end_at": row.end_at,
            }
        )

    start_date = to_app_tz(start_at).date()
    end_date = to_app_tz(end_at).date()

    leases = db.scalars(
        select(Lease).where(Lease.room_id == room_id, Lease.status == LeaseStatus.ACTIVE)
    ).all()
    for lease in leases:
        lease_end = lease.end_date or date.max
        if lease.start_date <= end_date and start_date <= lease_end:
            conflicts.append(
                {
                    "kind": "lease",
                    "lease_id": lease.id,
                    "start_at": lease.start_date,
                    "end_at": lease.end_date,
                }
            )

    # A mixed room is meant to host bookings alongside its resident team, so an
    # internal assignment there is not a clash for the internal audience. It
    # still is for the public one -- an outside group should not be sold a room
    # a team is sitting in.
    assignment_blocks = source == BookingSource.PUBLIC or (
        source != BookingSource.PUBLIC and _room_mode(db, room_id) != OccupancyMode.MIXED
    )
    if assignment_blocks:
        assignments = db.scalars(
            select(InternalRoomAssignment).where(InternalRoomAssignment.room_id == room_id)
        ).all()
        for assignment in assignments:
            assignment_end = assignment.end_date or date.max
            if assignment.start_date <= end_date and start_date <= assignment_end:
                conflicts.append(
                    {
                        "kind": "internal_assignment",
                        "assignment_id": assignment.id,
                        "start_at": assignment.start_date,
                        "end_at": assignment.end_date,
                    }
                )

    return conflicts


def _room_mode(db: Session, room_id: int) -> OccupancyMode | None:
    room = db.get(Room, room_id)
    return room.occupancy_mode if room else None


def lock_room_for_booking(db: Session, room_id: int) -> None:
    """Serialise booking attempts for one room.

    The guarantee is the ordering: lock -> check -> insert -> commit. Two
    concurrent requests for the same room cannot both pass the check, because
    the second blocks here until the first has committed and then re-reads.

    `SELECT ... FOR UPDATE` would not work: when there is no conflicting row
    there is nothing to lock, which is exactly the double-booking case. A
    transaction-scoped advisory lock has no such gap and is released
    automatically on commit or rollback.

    SQLite has no advisory locks, and its writer lock already serialises
    transactions, so this is a no-op there.
    """
    if db.bind is None or db.bind.dialect.name != "postgresql":
        return
    from sqlalchemy import text

    db.execute(
        text("SELECT pg_advisory_xact_lock(:ns, :room_id)"),
        {"ns": _ADVISORY_LOCK_NAMESPACE, "room_id": room_id},
    )


def ensure_available(
    db: Session,
    *,
    room_id: int,
    start_at: datetime,
    end_at: datetime,
    source: BookingSource = BookingSource.STAFF,
    exclude_booking_id: int | None = None,
) -> None:
    conflicts = find_conflicts(
        db,
        room_id=room_id,
        start_at=start_at,
        end_at=end_at,
        source=source,
        exclude_booking_id=exclude_booking_id,
    )
    if conflicts:
        raise RoomUnavailable(
            "This room is already taken for the selected time.",
            conflicts=[
                {"start_at": c["start_at"], "end_at": c["end_at"], "kind": c["kind"]} for c in conflicts
            ],
        )


# --------------------------------------------------------------------------
# Identity
# --------------------------------------------------------------------------


def resolve_public_requester(db: Session, requester: PublicRequesterInput) -> Party:
    """Find or create the EXTERNAL party for a public requester.

    Matching is confined to ``PartyType.EXTERNAL``. A public requester can
    therefore never be attached to a staff member, tenant or team that happens
    to share an email address -- silently filing a stranger's booking against a
    real person's record is the worst failure this feature could have, and it
    would leave no trace.

    The reverse direction is already safe: the Nextcloud sync only ever matches
    unlinked PERSON parties, so it cannot claim an EXTERNAL one either.
    """
    email = (requester.email or "").strip().lower()
    if not email:
        raise BookingError("An email address is required.", code="requester_email_required")

    existing = db.scalars(
        select(Party).where(
            Party.party_type == PartyType.EXTERNAL,
            func.lower(Party.email) == email,
        )
    ).first()

    display_name = " ".join(
        part for part in (requester.first_name, requester.last_name) if part
    ).strip()
    display_name = display_name or requester.organization or email

    if existing is not None:
        # Refresh contact details, but never overwrite a name with nothing.
        if display_name:
            existing.name = display_name
        existing.phone = requester.phone or existing.phone
        existing.street = requester.address or existing.street
        existing.is_active = True
        return existing

    party = Party(
        party_type=PartyType.EXTERNAL,
        name=display_name,
        email=email,
        phone=requester.phone,
        # The public form collects one free-text address. Splitting it into
        # street/postal/city with a parser would invent structure that is not
        # there; keeping it whole is honest and loses nothing.
        street=requester.address,
        is_active=True,
    )
    db.add(party)
    db.flush()
    return party


def resolve_member_party(db: Session, user: User) -> Party:
    """The contact record a member books against.

    Never falls back to creating one. A member whose link is missing is a sync
    problem, and silently creating a second party for them would fork their
    identity in a way that is tedious to unpick later.
    """
    if user.party_id is None:
        raise BookingError(
            "Your account is not linked to a contact record. Please contact an administrator.",
            code="member_not_linked",
        )
    party = db.get(Party, user.party_id)
    if party is None or not party.is_active:
        raise BookingError(
            "Your contact record is inactive. Please contact an administrator.",
            code="member_party_inactive",
        )
    return party


# --------------------------------------------------------------------------
# Validation of line items
# --------------------------------------------------------------------------


def validate_equipment(db: Session, room_id: int, lines: list[EquipmentLine]) -> None:
    if not lines:
        return
    available = {
        link.equipment_id: link.quantity
        for link in db.scalars(select(RoomEquipment).where(RoomEquipment.room_id == room_id)).all()
    }
    seen: set[int] = set()
    for line in lines:
        if line.equipment_id in seen:
            raise BookingError("Equipment requested twice.", code="equipment_duplicate")
        seen.add(line.equipment_id)
        if line.equipment_id not in available:
            raise BookingError("That equipment is not available in this room.", code="equipment_unknown")
        if line.quantity < 1:
            raise BookingError("Equipment quantity must be at least 1.", code="equipment_quantity")
        if line.quantity > available[line.equipment_id]:
            raise BookingError(
                "More of that equipment was requested than the room has.",
                code="equipment_quantity",
            )


def validate_services(db: Session, lines: list[ServiceLine]) -> None:
    if not lines:
        return
    ids = [line.service_id for line in lines]
    if len(set(ids)) != len(ids):
        raise BookingError("Service requested twice.", code="service_duplicate")
    found = {
        row.id
        for row in db.scalars(
            select(BookingService).where(BookingService.id.in_(ids), BookingService.is_active.is_(True))
        ).all()
    }
    for line in lines:
        if line.service_id not in found:
            raise BookingError("Unknown service requested.", code="service_unknown")
        if line.quantity < 1:
            raise BookingError("Service quantity must be at least 1.", code="service_quantity")


# --------------------------------------------------------------------------
# The writer
# --------------------------------------------------------------------------


def _snapshot(row: Booking) -> dict:
    return {
        "room_id": row.room_id,
        "party_id": row.party_id,
        "title": row.title,
        "start_at": row.start_at.isoformat() if row.start_at else None,
        "end_at": row.end_at.isoformat() if row.end_at else None,
        "status": row.status.value,
        "source": row.source.value,
        "purpose": row.purpose,
        "attendee_count": row.attendee_count,
        "notes": row.notes,
    }


def allocate_public_ref(db: Session) -> str:
    """Pick a reference that is not already taken.

    ~40 bits of entropy makes a collision vanishingly unlikely, but "unlikely"
    is not "handled": the reference app generated a 6-digit number with no
    check at all, so a duplicate surfaced as an unhandled 500 with the booking
    lost. The indexed pre-check catches the ordinary case; the UNIQUE index
    remains the backstop for a genuine race.
    """
    for _ in range(5):
        ref = generate_public_ref()
        taken = db.scalar(select(BookingRequest.id).where(BookingRequest.public_ref == ref))
        if taken is None:
            return ref
    raise BookingError("Could not allocate a booking reference.", code="ref_collision")


def create_booking(
    db: Session,
    *,
    room: Room,
    party: Party,
    data: BookingInput,
    source: BookingSource,
    status: BookingStatus,
    created_by_user_id: int | None = None,
    actor_user_id: int | None = None,
    requester: PublicRequesterInput | None = None,
    submitted_ip_hash: str | None = None,
    check_conflicts: bool = True,
    commit: bool = True,
) -> Booking:
    """Create a booking. The only path that writes one.

    ``check_conflicts`` is False only for the staff endpoint, which reports
    clashes as a warning rather than a refusal -- staff must still be able to
    record a competing request and decide between them later.
    """
    validate_room_for_source(room, source)
    start_at, end_at = normalize_timeframe(data.timeframe)

    if end_at <= start_at:
        raise BookingError("Booking end must be after start.", code="end_before_start")
    if (end_at - start_at) > timedelta(days=MAX_BOOKING_DURATION_DAYS):
        raise BookingError(
            f"A booking cannot run longer than {MAX_BOOKING_DURATION_DAYS} days.",
            code="duration_too_long",
        )
    if end_at <= app_now():
        raise BookingError("A booking cannot end in the past.", code="in_the_past")
    if data.attendee_count is not None and room.capacity is not None:
        if data.attendee_count > room.capacity:
            raise BookingError(
                "More attendees than the room holds.",
                code="over_capacity",
            )

    validate_equipment(db, room.id, data.equipment)
    validate_services(db, data.services)

    rate, days, charge = compute_cleaning_charge(room, start_at, end_at)

    if check_conflicts:
        lock_room_for_booking(db, room.id)
        ensure_available(db, room_id=room.id, start_at=start_at, end_at=end_at, source=source)

    booking = Booking(
        room_id=room.id,
        party_id=party.id,
        title=data.title,
        start_at=start_at,
        end_at=end_at,
        status=status,
        source=source,
        created_by_user_id=created_by_user_id,
        purpose=data.purpose,
        attendee_count=data.attendee_count,
        notes=data.notes,
    )
    db.add(booking)
    db.flush()

    request = BookingRequest(
        booking_id=booking.id,
        public_ref=allocate_public_ref(db),
        language=data.language,
        contact_person=data.contact_person,
        billing_info=data.billing_info,
        additional_info=data.additional_info,
        liability_insurance=data.liability_insurance,
        whole_day=data.timeframe.whole_day,
        cleaning_rate_daily=rate,
        cleaning_days=days,
        cleaning_charge=charge,
        submitted_ip_hash=submitted_ip_hash,
    )
    if requester is not None:
        request.requester_first_name = requester.first_name
        request.requester_last_name = requester.last_name
        request.requester_academic_title = requester.academic_title
        request.requester_organization = requester.organization
        request.requester_email = (requester.email or "").strip().lower() or None
        request.requester_phone = requester.phone
        request.requester_address = requester.address
    db.add(request)
    db.flush()

    for line in data.equipment:
        db.add(
            BookingEquipmentRequest(
                booking_id=booking.id,
                equipment_id=line.equipment_id,
                quantity=line.quantity,
                notes=line.notes,
            )
        )
    for line in data.services:
        db.add(
            BookingServiceRequest(
                booking_id=booking.id, service_id=line.service_id, quantity=line.quantity
            )
        )

    # actor_user_id is nullable, so a public request audits with no actor
    # rather than being attributed to nobody in particular.
    audit(db, entity=booking, action="created", actor_user_id=actor_user_id, after=_snapshot(booking))

    if commit:
        db.commit()
        db.refresh(booking)
    return booking


def approve_booking(db: Session, *, booking: Booking, actor_user_id: int | None) -> Booking:
    lock_room_for_booking(db, booking.room_id)
    ensure_available(
        db,
        room_id=booking.room_id,
        start_at=booking.start_at,
        end_at=booking.end_at,
        source=booking.source,
        exclude_booking_id=booking.id,
    )
    before = booking.status.value
    booking.status = BookingStatus.APPROVED
    audit(
        db,
        entity=booking,
        action="approved",
        actor_user_id=actor_user_id,
        before={"status": before},
        after={"status": booking.status.value},
    )
    db.commit()
    db.refresh(booking)
    return booking


def reject_booking(
    db: Session, *, booking: Booking, actor_user_id: int | None, reason: str | None = None
) -> Booking:
    before = booking.status.value
    booking.status = BookingStatus.REJECTED
    if booking.request is not None and reason:
        booking.request.staff_note = reason
    audit(
        db,
        entity=booking,
        action="rejected",
        actor_user_id=actor_user_id,
        before={"status": before},
        after={"status": booking.status.value, "staff_note": reason},
    )
    db.commit()
    db.refresh(booking)
    return booking


def cancel_booking(
    db: Session, *, booking: Booking, cancelled_by: str, actor_user_id: int | None
) -> Booking:
    """Cancel by status transition. Never a DELETE.

    The reference app hard-deleted on cancellation, destroying the record and
    any trace that the booking had existed.
    """
    before = booking.status.value
    booking.status = BookingStatus.CANCELLED
    if booking.request is not None:
        booking.request.cancelled_at = app_now()
        booking.request.cancelled_by = cancelled_by
        # Kill any outstanding manage link for this booking.
        booking.request.token_version += 1
    audit(
        db,
        entity=booking,
        action="cancelled",
        actor_user_id=actor_user_id,
        before={"status": before},
        after={"status": booking.status.value, "cancelled_by": cancelled_by},
    )
    db.commit()
    db.refresh(booking)
    return booking


def modify_booking(
    db: Session,
    *,
    booking: Booking,
    room: Room,
    data: BookingInput,
    actor_user_id: int | None,
    requester: PublicRequesterInput | None = None,
    reset_to_pending: bool = True,
) -> Booking:
    """Change an existing booking, re-running every rule that governed its creation.

    The reference app's modify route re-checked nothing, so the conflict check
    could be bypassed entirely by booking a free slot and then editing it onto
    a taken one. Here a modification is validated exactly as a creation is,
    including the availability check.

    A public modification also returns the booking to PENDING: the customer has
    changed what staff agreed to, so the agreement lapses. Skipping that would
    let someone get a quiet slot approved and then move it to a busy one.
    """
    validate_room_for_source(room, booking.source)
    start_at, end_at = normalize_timeframe(data.timeframe)

    if end_at <= start_at:
        raise BookingError("Booking end must be after start.", code="end_before_start")
    if (end_at - start_at) > timedelta(days=MAX_BOOKING_DURATION_DAYS):
        raise BookingError(
            f"A booking cannot run longer than {MAX_BOOKING_DURATION_DAYS} days.",
            code="duration_too_long",
        )
    if end_at <= app_now():
        raise BookingError("A booking cannot end in the past.", code="in_the_past")
    if data.attendee_count is not None and room.capacity is not None:
        if data.attendee_count > room.capacity:
            raise BookingError("More attendees than the room holds.", code="over_capacity")

    validate_equipment(db, room.id, data.equipment)
    validate_services(db, data.services)

    before = _snapshot(booking)

    lock_room_for_booking(db, room.id)
    ensure_available(
        db,
        room_id=room.id,
        start_at=start_at,
        end_at=end_at,
        source=booking.source,
        exclude_booking_id=booking.id,
    )

    booking.room_id = room.id
    booking.title = data.title
    booking.start_at = start_at
    booking.end_at = end_at
    booking.purpose = data.purpose or booking.purpose
    booking.attendee_count = data.attendee_count
    booking.notes = data.notes

    if reset_to_pending and booking.source == BookingSource.PUBLIC:
        booking.status = BookingStatus.PENDING

    request = booking.request
    if request is not None:
        rate, days, charge = compute_cleaning_charge(room, start_at, end_at)
        request.cleaning_rate_daily = rate
        request.cleaning_days = days
        request.cleaning_charge = charge
        request.whole_day = data.timeframe.whole_day
        request.contact_person = data.contact_person
        request.billing_info = data.billing_info
        request.additional_info = data.additional_info
        if requester is not None:
            request.requester_first_name = requester.first_name
            request.requester_last_name = requester.last_name
            request.requester_academic_title = requester.academic_title
            request.requester_organization = requester.organization
            request.requester_phone = requester.phone
            request.requester_address = requester.address
            # The email is deliberately NOT changed here. It is the address the
            # manage link was sent to and the key the party was resolved by;
            # letting the form rewrite it would hand the booking to someone
            # else. The reference app allowed exactly that.

    # Replace line items wholesale rather than diffing -- the form submits the
    # complete intended set every time.
    for existing in list(booking.equipment_requests):
        db.delete(existing)
    for existing in list(booking.service_requests):
        db.delete(existing)
    db.flush()
    for line in data.equipment:
        db.add(
            BookingEquipmentRequest(
                booking_id=booking.id,
                equipment_id=line.equipment_id,
                quantity=line.quantity,
                notes=line.notes,
            )
        )
    for line in data.services:
        db.add(
            BookingServiceRequest(
                booking_id=booking.id, service_id=line.service_id, quantity=line.quantity
            )
        )

    audit(
        db,
        entity=booking,
        action="modified",
        actor_user_id=actor_user_id,
        before=before,
        after=_snapshot(booking),
    )
    db.commit()
    db.refresh(booking)
    return booking
