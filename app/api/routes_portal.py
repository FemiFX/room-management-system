"""Member-facing booking API.

Everything here is scoped to the signed-in member. A member may see rooms they
can book, when those rooms are busy, and their own bookings -- never who else
booked, never another member's details, never anything from the admin surface.

Internal bookings are instant-confirm: they are created APPROVED after a
conflict check, so a member finds out immediately that a room is taken rather
than waiting for a staff decision.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.api.deps import require_member_or_staff, verify_csrf
from app.core.config import get_settings
from app.core.time_utils import app_now, to_app_tz
from app.db.session import get_db
from app.models.booking import Booking
from app.models.enums import BookingSource, BookingStatus, OccupancyMode
from app.models.equipment import RoomEquipment
from app.models.room import Room
from app.models.user import User
from app.schemas.common import ORMModel
from app.services.bookings import (
    BookingError,
    BookingInput,
    EquipmentLine,
    RoomUnavailable,
    ServiceLine,
    TimeframeInput,
    cancel_booking,
    create_booking,
    find_conflicts,
    resolve_member_party,
)

router = APIRouter(prefix="/portal", tags=["portal"], dependencies=[Depends(require_member_or_staff())])


class PortalEquipmentRead(BaseModel):
    equipment_id: int
    name: str
    max_quantity: int


class PortalRoomRead(ORMModel):
    id: int
    name: str
    room_code: str
    capacity: int | None
    public_description: str | None
    equipment: list[PortalEquipmentRead] = []


class BusyInterval(BaseModel):
    start_at: datetime
    end_at: datetime


class PortalBookingRead(ORMModel):
    id: int
    room_id: int
    title: str
    start_at: datetime
    end_at: datetime
    status: BookingStatus
    attendee_count: int | None
    notes: str | None


class PortalBookingCreate(BaseModel):
    room_id: int
    title: str = Field(min_length=1, max_length=255)
    start_at: datetime
    end_at: datetime
    whole_day: bool = False
    attendee_count: int | None = None
    purpose: str | None = None
    notes: str | None = None
    equipment: list[dict] = []
    services: list[dict] = []


def _bookable_rooms_stmt():
    """Rooms a member may book: internally bookable, or mixed."""
    return select(Room).where(
        Room.is_active.is_(True),
        (Room.bookable.is_(True)) | (Room.occupancy_mode == OccupancyMode.MIXED),
    )


def _conflict_error(exc: RoomUnavailable) -> HTTPException:
    return HTTPException(
        status_code=409,
        detail={
            "detail": str(exc),
            "code": exc.code,
            "conflicts": [
                {
                    "start_at": c["start_at"].isoformat() if c.get("start_at") else None,
                    "end_at": c["end_at"].isoformat() if c.get("end_at") else None,
                }
                for c in exc.conflicts
            ],
        },
    )


def _owned(db: Session, booking_id: int, user: User) -> Booking:
    """A member's own booking, or 404.

    404 rather than 403 on a mismatch: a 403 would confirm the booking exists.
    """
    booking = db.get(Booking, booking_id)
    if booking is None:
        raise HTTPException(status_code=404, detail="Booking not found.")
    owns = booking.created_by_user_id == user.id or (
        user.party_id is not None and booking.party_id == user.party_id
    )
    if not owns:
        raise HTTPException(status_code=404, detail="Booking not found.")
    return booking


@router.get("/rooms", response_model=list[PortalRoomRead])
def list_rooms(user: User = Depends(require_member_or_staff()), db: Session = Depends(get_db)):
    rooms = db.scalars(
        _bookable_rooms_stmt()
        .options(joinedload(Room.room_equipment).joinedload(RoomEquipment.equipment))
        .order_by(Room.name.asc())
    ).unique().all()
    return [
        PortalRoomRead(
            id=room.id,
            name=room.name,
            room_code=room.room_code,
            capacity=room.capacity,
            public_description=room.public_description,
            equipment=[
                PortalEquipmentRead(
                    equipment_id=link.equipment_id,
                    name=link.equipment.name,
                    max_quantity=link.quantity,
                )
                for link in room.room_equipment
                if link.equipment is not None
            ],
        )
        for room in rooms
    ]


@router.get("/availability", response_model=list[BusyInterval])
def availability(
    room_id: int,
    date_from: datetime = Query(alias="from"),
    date_to: datetime = Query(alias="to"),
    user: User = Depends(require_member_or_staff()),
    db: Session = Depends(get_db),
):
    """Busy intervals only.

    A member has no business knowing who booked a room or what for -- only
    that it is taken.
    """
    room = db.scalar(_bookable_rooms_stmt().where(Room.id == room_id))
    if room is None:
        raise HTTPException(status_code=404, detail="Room not found.")

    start = to_app_tz(date_from)
    end = to_app_tz(date_to)
    if end <= start:
        raise HTTPException(status_code=400, detail="Range end must be after start.")
    if (end - start) > timedelta(days=180):
        raise HTTPException(status_code=400, detail="Range is too wide.")

    rows = db.scalars(
        select(Booking).where(
            Booking.room_id == room_id,
            Booking.status == BookingStatus.APPROVED,
            Booking.start_at < end,
            Booking.end_at > start,
        )
    ).all()
    return [BusyInterval(start_at=row.start_at, end_at=row.end_at) for row in rows]


@router.get("/bookings", response_model=list[PortalBookingRead])
def my_bookings(user: User = Depends(require_member_or_staff()), db: Session = Depends(get_db)):
    stmt = select(Booking).where(Booking.created_by_user_id == user.id)
    if user.party_id is not None:
        stmt = select(Booking).where(
            (Booking.created_by_user_id == user.id) | (Booking.party_id == user.party_id)
        )
    return list(db.scalars(stmt.order_by(Booking.start_at.desc())).all())


@router.post("/bookings", response_model=PortalBookingRead, status_code=201, dependencies=[Depends(verify_csrf)])
def create(
    payload: PortalBookingCreate,
    user: User = Depends(require_member_or_staff()),
    db: Session = Depends(get_db),
):
    room = db.scalar(_bookable_rooms_stmt().where(Room.id == payload.room_id))
    if room is None:
        raise HTTPException(status_code=404, detail="Room not found.")

    settings = get_settings()
    start = to_app_tz(payload.start_at)
    if start > app_now() + timedelta(days=settings.member_booking_max_horizon_days):
        raise HTTPException(
            status_code=400,
            detail=f"Bookings can be made up to {settings.member_booking_max_horizon_days} days ahead.",
        )
    if not payload.whole_day:
        duration = to_app_tz(payload.end_at) - start
        if duration > timedelta(hours=settings.member_booking_max_duration_hours):
            raise HTTPException(
                status_code=400,
                detail=f"A booking can run for at most {settings.member_booking_max_duration_hours} hours.",
            )

    try:
        party = resolve_member_party(db, user)
    except BookingError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    data = BookingInput(
        room_id=room.id,
        title=payload.title,
        timeframe=TimeframeInput(
            start_at=payload.start_at, end_at=payload.end_at, whole_day=payload.whole_day
        ),
        purpose=payload.purpose,
        attendee_count=payload.attendee_count,
        notes=payload.notes,
        language=user.preferred_language,
        equipment=[
            EquipmentLine(int(item["equipment_id"]), int(item.get("quantity", 1)))
            for item in payload.equipment
        ],
        services=[
            ServiceLine(int(item["service_id"]), int(item.get("quantity", 1)))
            for item in payload.services
        ],
    )

    try:
        booking = create_booking(
            db,
            room=room,
            party=party,
            data=data,
            source=BookingSource.INTERNAL,
            # Instant confirm: the member is told now, not after a review.
            status=BookingStatus.APPROVED,
            created_by_user_id=user.id,
            actor_user_id=user.id,
        )
    except RoomUnavailable as exc:
        raise _conflict_error(exc) from exc
    except BookingError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    from app.services.booking_notifications import notify_member_booking

    notify_member_booking(booking)
    return booking


@router.post("/bookings/{booking_id}/cancel", response_model=PortalBookingRead, dependencies=[Depends(verify_csrf)])
def cancel(
    booking_id: int,
    user: User = Depends(require_member_or_staff()),
    db: Session = Depends(get_db),
):
    booking = _owned(db, booking_id, user)
    # SQLite hands back naive datetimes, so normalise before comparing.
    if to_app_tz(booking.end_at) <= app_now():
        raise HTTPException(status_code=400, detail="That booking has already ended.")

    cancelled = cancel_booking(db, booking=booking, cancelled_by="member", actor_user_id=user.id)

    from app.services.booking_notifications import notify_member_booking

    notify_member_booking(cancelled, cancelled=True)
    return cancelled
