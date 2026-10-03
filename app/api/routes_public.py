"""Unauthenticated public booking API.

This is the only externally-reachable read path in RMS, so every response here
is built from a purpose-made schema rather than reusing an admin one. The
reference app published every booking's event title and room to the world on
an open-CORS endpoint; this publishes busy intervals and nothing else.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.core.time_utils import to_app_tz
from app.db.session import get_db
from app.models.booking import Booking
from app.models.booking_service import BookingService
from app.models.enums import BookingStatus
from app.models.equipment import RoomEquipment
from app.models.room import Room
from app.services.bookings import (
    BookingError,
    TimeframeInput,
    compute_cleaning_charge,
    normalize_timeframe,
)

# No auth dependency: this router is deliberately public. Everything it
# exposes is safe for anonymous eyes, and every write it offers is separately
# gated on a signed token.
router = APIRouter(prefix="/public", tags=["public"])

MAX_AVAILABILITY_WINDOW_DAYS = 180


class PublicEquipmentRead(BaseModel):
    equipment_id: int
    name: str
    max_quantity: int


class PublicServiceRead(BaseModel):
    service_id: int
    code: str
    name: str
    description: str | None


class PublicRoomRead(BaseModel):
    """Deliberately not RoomRead.

    Floor and building ids, meter_number, occupancy_mode, rentable and lease
    data are all internal and none of them belong on a public page.
    """

    id: int
    name: str
    capacity: int | None
    description: str | None
    cleaning_rate_daily: Decimal | None
    equipment: list[PublicEquipmentRead]


class BusyInterval(BaseModel):
    start_at: datetime
    end_at: datetime


class QuoteRead(BaseModel):
    cleaning_rate_daily: Decimal | None
    cleaning_days: int | None
    cleaning_charge: Decimal | None
    currency: str = "EUR"


def _public_rooms_stmt():
    return select(Room).where(Room.is_active.is_(True), Room.public_bookable.is_(True))


@router.get("/rooms", response_model=list[PublicRoomRead])
def list_rooms(db: Session = Depends(get_db)):
    rooms = db.scalars(
        _public_rooms_stmt()
        .options(joinedload(Room.room_equipment).joinedload(RoomEquipment.equipment))
        .order_by(Room.name.asc())
    ).unique().all()
    return [
        PublicRoomRead(
            id=room.id,
            name=room.name,
            capacity=room.capacity,
            description=room.public_description,
            cleaning_rate_daily=room.cleaning_rate_daily,
            equipment=[
                PublicEquipmentRead(
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


@router.get("/services", response_model=list[PublicServiceRead])
def list_services(db: Session = Depends(get_db)):
    services = db.scalars(
        select(BookingService)
        .where(BookingService.is_active.is_(True))
        .order_by(BookingService.sort_order.asc(), BookingService.name.asc())
    ).all()
    return [
        PublicServiceRead(
            service_id=service.id,
            code=service.code,
            name=service.name,
            description=service.description,
        )
        for service in services
    ]


@router.get("/rooms/{room_id}/availability", response_model=list[BusyInterval])
def availability(
    room_id: int,
    date_from: datetime = Query(alias="from"),
    date_to: datetime = Query(alias="to"),
    db: Session = Depends(get_db),
):
    """When a public room is busy. Nothing about who or why.

    Restricted to publicly bookable rooms: answering for any room id would
    turn this into an occupancy oracle for the whole building.
    """
    room = db.scalar(_public_rooms_stmt().where(Room.id == room_id))
    if room is None:
        raise HTTPException(status_code=404, detail="Room not found.")

    start = to_app_tz(date_from)
    end = to_app_tz(date_to)
    if end <= start:
        raise HTTPException(status_code=400, detail="Range end must be after start.")
    if (end - start) > timedelta(days=MAX_AVAILABILITY_WINDOW_DAYS):
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


@router.get("/quote", response_model=QuoteRead)
def quote(
    room_id: int,
    start: datetime,
    end: datetime,
    whole_day: bool = False,
    db: Session = Depends(get_db),
):
    """The cleaning charge for a proposed booking.

    This is how the form can *show* the price without ever being *trusted*
    with it: the authoritative figure is recomputed at submit, from the same
    function.
    """
    room = db.scalar(_public_rooms_stmt().where(Room.id == room_id))
    if room is None:
        raise HTTPException(status_code=404, detail="Room not found.")
    try:
        start_at, end_at = normalize_timeframe(
            TimeframeInput(start_at=start, end_at=end, whole_day=whole_day)
        )
    except BookingError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if end_at <= start_at:
        raise HTTPException(status_code=400, detail="Booking end must be after start.")

    rate, days, charge = compute_cleaning_charge(room, start_at, end_at)
    return QuoteRead(cleaning_rate_daily=rate, cleaning_days=days, cleaning_charge=charge)
