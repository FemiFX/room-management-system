from __future__ import annotations

from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.api.deps import get_current_user, require_role, verify_csrf
from app.db.session import get_db
from app.models.booking import Booking
from app.models.enums import BookingSource, BookingStatus, Role
from app.models.party import Party
from app.models.room import Room
from app.models.user import User
from app.schemas.domain import (
    BookingConflict,
    BookingCreate,
    BookingCreateRead,
    BookingRead,
    BookingUpdate,
)
from app.services.audit import audit
from app.services.booking_documents import (
    DocumentRejected,
    find_certificate,
    store_certificate,
)
from app.services.bookings import (
    BookingError,
    BookingInput,
    RoomUnavailable,
    TimeframeInput,
    cancel_booking,
    create_booking,
    find_conflicts,
    validate_room_for_source,
)
from app.services.bookings import approve_booking as approve_booking_service
from app.services.bookings import reject_booking as reject_booking_service

router = APIRouter(tags=["bookings"])

_STAFF_WRITE = (Role.SUPER_ADMIN, Role.ADMIN, Role.EDITOR)


def _datetime(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _booking_snapshot(row: Booking) -> dict:
    return {
        "room_id": row.room_id,
        "party_id": row.party_id,
        "title": row.title,
        "start_at": _datetime(row.start_at),
        "end_at": _datetime(row.end_at),
        "status": row.status.value,
        "source": row.source.value,
        "purpose": row.purpose,
        "attendee_count": row.attendee_count,
        "notes": row.notes,
    }


def _unavailable(exc: RoomUnavailable) -> HTTPException:
    """409 with the clashing intervals, so the UI can name the clash.

    A bare 400 leaves the user guessing which of their choices was wrong.
    """
    return HTTPException(
        status_code=409,
        detail={
            "detail": str(exc),
            "code": exc.code,
            "conflicts": [
                {
                    "kind": c["kind"],
                    "start_at": c["start_at"].isoformat() if c.get("start_at") else None,
                    "end_at": c["end_at"].isoformat() if c.get("end_at") else None,
                }
                for c in exc.conflicts
            ],
        },
    )


@router.get("/bookings", response_model=list[BookingRead])
def list_bookings(
    _: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return list(db.scalars(select(Booking).order_by(Booking.start_at.asc())).all())


class CalendarEventRead(BaseModel):
    """One booking, shaped for the admin calendar.

    Staff-only, so unlike the public availability feed this carries the title
    and the party. `resourceIds` drives the rooms-as-lanes views.
    """

    id: str
    title: str
    start: datetime
    end: datetime
    resourceIds: list[str]
    backgroundColor: str
    extendedProps: dict


class CalendarResourceRead(BaseModel):
    id: str
    title: str


#: Status drives colour. Kept in step with booking_status_badge so the calendar
#: and the list do not tell different stories about the same booking.
_STATUS_COLOURS = {
    BookingStatus.PENDING: "#D8A843",
    BookingStatus.APPROVED: "#2F6E47",
    BookingStatus.REJECTED: "#E85D75",
    BookingStatus.CANCELLED: "#8f8c87",
    BookingStatus.COMPLETED: "#4A9EDD",
}


@router.get("/bookings/calendar-resources", response_model=list[CalendarResourceRead])
def calendar_resources(
    _: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    rooms = db.scalars(
        select(Room).where(Room.is_active.is_(True)).order_by(Room.name.asc())
    ).all()
    return [CalendarResourceRead(id=str(room.id), title=room.name) for room in rooms]


@router.get("/bookings/calendar-events", response_model=list[CalendarEventRead])
def calendar_events(
    start: datetime,
    end: datetime,
    _: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Bookings overlapping a window, for the admin calendar.

    Cancelled and rejected bookings are excluded: they occupy nothing, and
    showing them would make a free room look busy.
    """
    from app.core.time_utils import to_app_tz

    window_start = to_app_tz(start)
    window_end = to_app_tz(end)
    if window_end <= window_start:
        raise HTTPException(status_code=400, detail="Range end must be after start.")
    if (window_end - window_start) > timedelta(days=400):
        raise HTTPException(status_code=400, detail="Range is too wide.")

    rows = db.scalars(
        select(Booking)
        .options(joinedload(Booking.room), joinedload(Booking.party), joinedload(Booking.request))
        .where(
            Booking.status.in_([BookingStatus.PENDING, BookingStatus.APPROVED, BookingStatus.COMPLETED]),
            Booking.start_at < window_end,
            Booking.end_at > window_start,
        )
        .order_by(Booking.start_at.asc())
    ).unique().all()

    return [
        CalendarEventRead(
            id=str(row.id),
            title=row.title,
            start=row.start_at,
            end=row.end_at,
            resourceIds=[str(row.room_id)],
            backgroundColor=_STATUS_COLOURS.get(row.status, "#6b6865"),
            extendedProps={
                "status": row.status.value,
                "source": row.source.value,
                "room": row.room.name if row.room else "",
                "room_code": row.room.room_code if row.room else "",
                "party": row.party.name if row.party else "",
                "attendees": row.attendee_count,
                "public_ref": row.request.public_ref if row.request else None,
                # Only a confirmed booking holds a slot, so only a confirmed
                # one is worth dragging; the UI greys the rest.
                "editable": row.status in (BookingStatus.PENDING, BookingStatus.APPROVED),
            },
        )
        for row in rows
    ]


@router.post("/bookings", response_model=BookingCreateRead, status_code=201, dependencies=[Depends(verify_csrf)])
def create_booking_endpoint(
    payload: BookingCreate,
    actor: User = Depends(require_role(*_STAFF_WRITE)),
    db: Session = Depends(get_db),
):
    room = db.get(Room, payload.room_id)
    if room is None:
        raise HTTPException(status_code=404, detail="Room not found.")
    party = db.get(Party, payload.party_id)
    if party is None:
        raise HTTPException(status_code=404, detail="Party not found.")

    data = BookingInput(
        room_id=payload.room_id,
        title=payload.title,
        timeframe=TimeframeInput(start_at=payload.start_at, end_at=payload.end_at),
        purpose=payload.purpose,
        attendee_count=payload.attendee_count,
        notes=payload.notes,
        language=actor.preferred_language,
    )

    try:
        # Staff bookings are not refused on a clash -- they still land as
        # PENDING, and the conflict check bites at approval. Refusing here
        # would stop staff recording a legitimate competing request.
        booking = create_booking(
            db,
            room=room,
            party=party,
            data=data,
            source=BookingSource.STAFF,
            status=BookingStatus.PENDING,
            created_by_user_id=actor.id,
            actor_user_id=actor.id,
            check_conflicts=False,
        )
    except BookingError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    conflicts = find_conflicts(
        db,
        room_id=booking.room_id,
        start_at=booking.start_at,
        end_at=booking.end_at,
        source=BookingSource.STAFF,
        exclude_booking_id=booking.id,
    )
    result = BookingCreateRead.model_validate(booking)
    result.conflicts = [
        BookingConflict(kind=c["kind"], start_at=c.get("start_at"), end_at=c.get("end_at"))
        for c in conflicts
    ]
    return result


@router.patch("/bookings/{booking_id}", response_model=BookingRead, dependencies=[Depends(verify_csrf)])
def update_booking(
    booking_id: int,
    payload: BookingUpdate,
    actor: User = Depends(require_role(*_STAFF_WRITE)),
    db: Session = Depends(get_db),
):
    row = db.get(Booking, booking_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Booking not found.")

    fields = payload.model_dump(exclude_unset=True)
    new_status = fields.pop("status", None)

    # A pure status change routes through the service so approval, rejection
    # and cancellation all get their conflict re-check, staff note and
    # token revocation. This is the path the admin UI actually uses.
    if new_status is not None and not fields:
        try:
            if new_status == BookingStatus.APPROVED:
                return approve_booking_service(db, booking=row, actor_user_id=actor.id)
            if new_status == BookingStatus.REJECTED:
                return reject_booking_service(db, booking=row, actor_user_id=actor.id)
            if new_status == BookingStatus.CANCELLED:
                return cancel_booking(db, booking=row, cancelled_by="staff", actor_user_id=actor.id)
        except RoomUnavailable as exc:
            raise _unavailable(exc) from exc
        except BookingError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    before = _booking_snapshot(row)

    if "room_id" in fields:
        target = db.get(Room, fields["room_id"])
        if target is None:
            raise HTTPException(status_code=404, detail="Room not found.")
        try:
            validate_room_for_source(target, row.source)
        except BookingError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    for key, value in fields.items():
        setattr(row, key, value)
    if new_status is not None:
        row.status = new_status

    if row.end_at <= row.start_at:
        raise HTTPException(status_code=400, detail="Booking end must be after start.")

    if row.status == BookingStatus.APPROVED:
        try:
            from app.services.bookings import ensure_available

            ensure_available(
                db,
                room_id=row.room_id,
                start_at=row.start_at,
                end_at=row.end_at,
                source=row.source,
                exclude_booking_id=row.id,
            )
        except RoomUnavailable as exc:
            db.rollback()
            raise _unavailable(exc) from exc
        except BookingError as exc:
            db.rollback()
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    audit(db, entity=row, action="updated", actor_user_id=actor.id, before=before, after=_booking_snapshot(row))
    db.commit()
    db.refresh(row)
    return row


@router.post("/bookings/{booking_id}/approve", response_model=BookingRead, dependencies=[Depends(verify_csrf)])
def approve_booking(
    booking_id: int,
    actor: User = Depends(require_role(*_STAFF_WRITE)),
    db: Session = Depends(get_db),
):
    row = db.get(Booking, booking_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Booking not found.")
    try:
        return approve_booking_service(db, booking=row, actor_user_id=actor.id)
    except RoomUnavailable as exc:
        raise _unavailable(exc) from exc
    except BookingError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/bookings/{booking_id}/reject", response_model=BookingRead, dependencies=[Depends(verify_csrf)])
def reject_booking(
    booking_id: int,
    payload: dict | None = None,
    actor: User = Depends(require_role(*_STAFF_WRITE)),
    db: Session = Depends(get_db),
):
    """Reject, optionally with a reason the requester sees in their email."""
    row = db.get(Booking, booking_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Booking not found.")
    reason = (payload or {}).get("reason")
    return reject_booking_service(db, booking=row, actor_user_id=actor.id, reason=reason)


# --------------------------------------------------------------------------
# The liability certificate
# --------------------------------------------------------------------------


@router.post("/bookings/{booking_id}/insurance", status_code=201, dependencies=[Depends(verify_csrf)])
async def upload_insurance_certificate(
    booking_id: int,
    file: UploadFile = File(...),
    actor: User = Depends(require_role(*_STAFF_WRITE)),
    db: Session = Depends(get_db),
):
    """Staff attaching the certificate themselves.

    Requesters upload their own through the manage link; this is for the ones
    that arrive as an email attachment instead, which is most of them.
    """
    booking = db.get(Booking, booking_id)
    if booking is None:
        raise HTTPException(status_code=404, detail="Booking not found.")

    blob = await file.read()
    try:
        row = store_certificate(
            db,
            booking,
            filename=file.filename,
            content_type=file.content_type,
            blob=blob,
            uploaded_by_user_id=actor.id,
        )
    except DocumentRejected as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"id": row.id, "original_filename": row.original_filename, "file_size": row.file_size}


@router.delete("/bookings/{booking_id}/insurance", status_code=204, dependencies=[Depends(verify_csrf)])
def delete_insurance_certificate(
    booking_id: int,
    actor: User = Depends(require_role(*_STAFF_WRITE)),
    db: Session = Depends(get_db),
):
    from app.storage.minio_client import delete_object

    row = find_certificate(db, booking_id)
    if row is None:
        raise HTTPException(status_code=404, detail="No certificate on file.")
    object_key = row.object_key
    audit(
        db,
        entity="document",
        entity_id=row.id,
        action="deleted",
        actor_user_id=actor.id,
        before={"booking_id": booking_id, "original_filename": row.original_filename},
    )
    db.delete(row)
    db.commit()
    # After the commit, for the same reason store_certificate waits: a failed
    # commit must not leave a row pointing at a file that is already gone.
    try:
        delete_object(object_key=object_key)
    except Exception:
        pass


@router.post("/bookings/{booking_id}/insurance/remind", dependencies=[Depends(verify_csrf)])
def remind_about_insurance(
    booking_id: int,
    actor: User = Depends(require_role(*_STAFF_WRITE)),
    db: Session = Depends(get_db),
):
    """Send the requester their manage link again, so they can upload it.

    Deliberately the *same* link they already have rather than a new
    single-purpose one: one credential per booking is enough to reason about,
    and it is already revocable through token_version.
    """
    from app.services.booking_notifications import notify
    from app.services.booking_tokens import manage_url

    booking = db.scalars(
        select(Booking)
        .options(joinedload(Booking.request), joinedload(Booking.room))
        .where(Booking.id == booking_id)
    ).unique().one_or_none()
    if booking is None:
        raise HTTPException(status_code=404, detail="Booking not found.")
    if booking.request is None or not booking.request.requester_email:
        raise HTTPException(status_code=400, detail="This booking has no requester to write to.")

    link = manage_url(
        booking_request_id=booking.request.id, token_version=booking.request.token_version
    )
    notify(booking, "public_booking_manage_link", manage_url=link)
    audit(db, entity=booking, action="insurance_reminder_sent", actor_user_id=actor.id)
    db.commit()
    return {"sent_to": booking.request.requester_email}
