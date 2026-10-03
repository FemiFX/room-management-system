from __future__ import annotations

import calendar as _calendar
from datetime import date, datetime, time, timedelta

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload, selectinload

from app.core.templating import templates
from app.db.session import get_db
from app.models.booking import Booking
from app.models.document import Document
from app.models.enums import BookingStatus, DocumentType, PartyType
from app.models.booking_request import BookingEquipmentRequest, BookingServiceRequest
from app.models.audit_log import AuditLog
from app.core.time_utils import app_now, app_timezone, to_app_tz
from app.models.booking_service import BookingService
from app.models.equipment import Equipment, RoomEquipment
from app.models.room_service import RoomService
from app.models.room import Room
from app.services.bookings import find_conflicts
from app.services.calendar import build_month, resolve_month
from app.views.deps import base_admin_context, get_authenticated_user

router = APIRouter()


# --------------------------------------------------------------------------
# The bookings page: one page, two views
# --------------------------------------------------------------------------

def _parse_day(raw: str | None) -> date | None:
    try:
        return date.fromisoformat(raw) if raw else None
    except ValueError:
        return None


def _resolve_range(
    key: str | None, raw_from: str | None, raw_to: str | None
) -> tuple[str, datetime, datetime, date, date]:
    """Turn the picker's choice into a half-open ``[start, end)`` window.

    Returns the *resolved* key as well, because a custom range with unusable
    dates falls back rather than showing an empty page with no explanation.
    """
    tz = app_timezone()
    now = app_now()
    today = now.date()

    def at(day: date) -> datetime:
        return datetime.combine(day, time.min, tzinfo=tz)

    if key == "custom":
        first = _parse_day(raw_from)
        last = _parse_day(raw_to)
        if first and last and last >= first:
            return "custom", at(first), at(last + timedelta(days=1)), first, last
        key = None  # unusable input: fall through to the default

    if key == "week":
        first = today - timedelta(days=today.weekday())
        last = first + timedelta(days=6)
    elif key == "month":
        first = today.replace(day=1)
        last = today.replace(day=_calendar.monthrange(today.year, today.month)[1])
    elif key == "upcoming":
        first = today
        last = today + timedelta(days=365)
    else:
        # The window this page has always shown. Still the default, so nobody's
        # muscle memory breaks.
        key = "days30"
        first = today - timedelta(days=30)
        last = today + timedelta(days=30)

    return key, at(first), at(last + timedelta(days=1)), first, last


def _resolve_status(raw: str | None) -> BookingStatus | None:
    try:
        return BookingStatus(raw) if raw else None
    except ValueError:
        return None


@router.get("/bookings", response_class=HTMLResponse)
def bookings_list(
    request: Request,
    view: str | None = None,
    range: str | None = Query(default=None),
    status: str | None = Query(default=None),
    kind: str = "all",
    range_from: str | None = Query(default=None, alias="from"),
    range_to: str | None = Query(default=None, alias="to"),
    year: int | None = None,
    month: int | None = None,
    db: Session = Depends(get_db),
):
    """Bookings as a list or as a calendar -- the same set, shown two ways.

    They used to be two pages. The calendar is not a separate concern, it is a
    second reading of the same rows, so it lives here behind ``?view=``.
    """
    user = get_authenticated_user(request, db)
    if not user:
        return RedirectResponse(url="/auth/login", status_code=303)

    # Coming back from a booking -- or from the sidebar -- lands on the view
    # you were last in. Opening a booking from the calendar and returning to
    # the list you never chose is the kind of small loss that makes people
    # stop using the calendar at all. An explicit ?view= always wins.
    if view in ("list", "calendar"):
        request.session["bookings_view"] = view
    else:
        view = request.session.get("bookings_view", "list")

    _remember_list(request)

    if view == "calendar":
        return _calendar_view(request, user, db, year=year, month=month)

    range_key, window_start, window_end, first_day, last_day = _resolve_range(
        range, range_from, range_to
    )

    def loaded(stmt):
        return stmt.options(
            joinedload(Booking.room),
            joinedload(Booking.party),
            # Eager-loaded: the list renders the public reference per row, and
            # a lazy load would be one query per booking.
            joinedload(Booking.request),
            joinedload(Booking.documents),
        )

    # Everything that has been decided, inside the chosen period.
    decided = list(
        db.scalars(
            loaded(select(Booking))
            .where(
                Booking.status != BookingStatus.PENDING,
                Booking.start_at < window_end,
                Booking.end_at > window_start,
            )
            .order_by(Booking.start_at.asc())
        ).unique().all()
    )

    # What waits is NOT filtered by the period. A request for next spring is
    # still a request you owe an answer to today, and a queue that a filter
    # can hide is the queue people stop trusting.
    waiting = list(
        db.scalars(
            loaded(select(Booking))
            .where(Booking.status == BookingStatus.PENDING)
            .order_by(Booking.created_at.asc())
        ).unique().all()
    )

    def of_kind(rows: list[Booking]) -> list[Booking]:
        if kind == "external":
            return [b for b in rows if _is_external(b)]
        if kind == "internal":
            return [b for b in rows if not _is_external(b)]
        return rows

    if kind not in ("external", "internal"):
        kind = "all"
    waiting = of_kind(waiting)
    decided = of_kind(decided)

    now = app_now()
    upcoming = [
        b for b in decided if b.status == BookingStatus.APPROVED and to_app_tz(b.end_at) >= now
    ]
    settled = [b for b in decided if b not in upcoming]
    settled.reverse()

    groups = [
        {"key": "waiting", "rows": waiting, "open": True},
        {"key": "upcoming", "rows": upcoming, "open": True},
        {"key": "settled", "rows": settled, "open": False},
    ]
    bookings = waiting + upcoming + settled

    ctx = base_admin_context(
        request, user, db, active_path="/bookings",
        bookings=bookings,
        now=app_now(),
        range_key=range_key,
        range_from=first_day.isoformat(),
        range_to=last_day.isoformat(),
        range_label=_range_label(first_day, last_day),
        kind_key=kind,
        groups=groups,
        waiting_count=len(waiting),
        upcoming_count=len(upcoming),
        insurance_of=_insurance_states(bookings),
    )
    return templates.TemplateResponse(request, "admin/bookings/list.html", ctx)


def _range_label(first: date, last: date) -> str:
    """A plain reading of the window, so nobody has to infer it from the rows.

    The old page said "±30 days" in a subtitle and showed whatever it showed;
    a list whose window is invisible is exactly how you end up wondering why
    it is only showing you Friday and Saturday.
    """
    if first.year == last.year and first.month == last.month:
        return f"{first.day:02d}.–{last.day:02d}.{last.month:02d}.{last.year}"
    return (
        f"{first.day:02d}.{first.month:02d}.{first.year} – "
        f"{last.day:02d}.{last.month:02d}.{last.year}"
    )


def _calendar_view(request: Request, user, db: Session, *, year: int | None, month: int | None):
    """Every room, pending and confirmed, with titles. Staff see the lot."""
    year, month = resolve_month(year, month)
    rooms = list(db.scalars(select(Room).where(Room.is_active.is_(True))).all())
    grid = build_month(
        db,
        year=year,
        month=month,
        rooms=rooms,
        statuses={BookingStatus.APPROVED, BookingStatus.PENDING},
        include_titles=True,
    )
    ctx = base_admin_context(request, user, db, active_path="/bookings", month=grid)
    return templates.TemplateResponse(request, "admin/bookings/calendar.html", ctx)


@router.get("/bookings/calendar", response_class=HTMLResponse)
def bookings_calendar_redirect(request: Request):
    """The calendar's old address.

    Kept, and kept working: notification rows, emails and anybody's bookmarks
    point here. Query parameters ride along so a link to a specific month
    still lands on that month.
    """
    query = str(request.url.query)
    suffix = f"&{query}" if query else ""
    return RedirectResponse(url=f"/bookings?view=calendar{suffix}", status_code=307)


def _insurance_states(bookings: list[Booking]) -> dict[int, str]:
    """``{booking_id: state}`` for the list's certificate column."""
    return {
        booking.id: insurance_state(
            booking,
            next(
                (d for d in booking.documents if d.document_type == DocumentType.INSURANCE),
                None,
            ),
        )
        for booking in bookings
    }


def _remember_list(request) -> None:
    """Keep the list a booking was opened from, filters included.

    "Zurück" that always lands on the same page throws away the period, the
    status and the tab someone had set -- and after a decision they want to
    be back where the rest of the queue is, not at the top of everything.
    """
    query = str(request.url.query)
    request.session["bookings_back"] = request.url.path + (f"?{query}" if query else "")


def _is_external(booking: Booking) -> bool:
    """Whose booking it is, not which door it came through.

    A request phoned in and typed by staff is still an external one: it needs
    the same yes, the same certificate and the same invoice as one from the
    public form.
    """
    return bool(booking.party and booking.party.party_type == PartyType.EXTERNAL)


@router.get("/bookings/requests", response_class=HTMLResponse)
def bookings_requests(request: Request, kind: str = "all"):
    """The requests inbox was its own page for a day.

    It is the first group of the booking list now -- same rows, same actions,
    one place. Kept as a redirect so links, bookmarks and a browser's history
    still land somewhere sensible.
    """
    suffix = f"?kind={kind}" if kind in ("external", "internal") else ""
    return RedirectResponse(url=f"/bookings{suffix}", status_code=307)


@router.get("/bookings/setup", response_class=HTMLResponse)
def bookings_setup(request: Request, db: Session = Depends(get_db)):
    """What a room can be booked with: equipment, per-room stock, and services.

    One tab per room, because setting a room up is a room-at-a-time job. Each
    panel lists the WHOLE catalogue rather than only what the room already
    has: an item the room lacks sits greyed at zero, and the plus turns it on.
    A list of only what is present cannot answer "what is missing here", which
    is the question someone setting a room up actually has.
    """
    user = get_authenticated_user(request, db)
    if not user:
        return RedirectResponse(url="/auth/login", status_code=303)

    equipment = list(db.scalars(select(Equipment).order_by(Equipment.name.asc())).all())
    # Only active services: an inactive one is off every form, so offering to
    # switch it on for one room would promise something that cannot happen.
    services = list(
        db.scalars(
            select(BookingService)
            .where(BookingService.is_active.is_(True))
            .order_by(BookingService.sort_order.asc(), BookingService.name.asc())
        ).all()
    )
    rooms = db.scalars(
        select(Room)
        .where(Room.is_active.is_(True))
        .options(
            selectinload(Room.room_equipment).joinedload(RoomEquipment.equipment),
            selectinload(Room.service_links).joinedload(RoomService.service),
        )
        .order_by(Room.name.asc())
    ).unique().all()

    tabs = []
    for room in rooms:
        links = {link.equipment_id: link for link in room.room_equipment}
        offers = {link.service_id: link for link in room.service_links}
        tabs.append(
            {
                "room": room,
                # What the room has first, then the rest of the catalogue: the
                # room's own kit is what someone came to look at, and the zero
                # rows underneath are the offer to add more.
                "equipment": sorted(
                    ({"equipment": item, "link": links.get(item.id)} for item in equipment),
                    key=lambda row: (row["link"] is None, row["equipment"].name.lower()),
                ),
                "equipment_present": len(links),
                "services": [
                    {"service": service, "link": offers.get(service.id)} for service in services
                ],
                "services_offered": sum(1 for service in services if service.id in offers),
            }
        )

    ctx = base_admin_context(
        request, user, db, active_path="/bookings/setup",
        equipment=equipment,
        tabs=tabs,
        services=services,
    )
    return templates.TemplateResponse(request, "admin/bookings/setup.html", ctx)


def _tally(db: Session, column, source) -> dict[int, int]:
    """``{id: count}`` in one grouped query, rather than one query per row."""
    rows = db.execute(select(column, func.count()).select_from(source).group_by(column)).all()
    return {key: int(count) for key, count in rows}


@router.get("/bookings/catalogue", response_class=HTMLResponse)
def bookings_catalogue(request: Request, db: Session = Depends(get_db)):
    """The catalogue: what kinds of thing exist at all, not where they stand.

    Must stay above ``/bookings/{booking_id}`` -- otherwise "catalogue" is
    read as a booking id and the page redirects to the list.

    The reference app had no such list: every room typed its own equipment
    names, so "Beamer" existed in five spellings. This is that missing list,
    with the usage counts that say whether a row can safely be deleted.
    """
    user = get_authenticated_user(request, db)
    if not user:
        return RedirectResponse(url="/auth/login", status_code=303)

    equipment = list(db.scalars(select(Equipment).order_by(Equipment.name.asc())).all())
    services = list(
        db.scalars(
            select(BookingService).order_by(
                BookingService.sort_order.asc(), BookingService.name.asc()
            )
        ).all()
    )

    equipment_rooms = _tally(db, RoomEquipment.equipment_id, RoomEquipment)
    equipment_requested = _tally(db, BookingEquipmentRequest.equipment_id, BookingEquipmentRequest)
    equipment_stock = {
        key: int(total or 0)
        for key, total in db.execute(
            select(RoomEquipment.equipment_id, func.sum(RoomEquipment.quantity))
            .group_by(RoomEquipment.equipment_id)
        ).all()
    }
    service_rooms = _tally(db, RoomService.service_id, RoomService)
    service_requested = _tally(db, BookingServiceRequest.service_id, BookingServiceRequest)

    # Grouped by category so that "Technik" and "Mobiliar" do not interleave.
    # Uncategorised entries go last: they are the ones nobody has sorted yet.
    by_category: dict[str | None, list] = {}
    for item in equipment:
        by_category.setdefault(item.category or None, []).append(
            {
                "item": item,
                "rooms": equipment_rooms.get(item.id, 0),
                "stock": equipment_stock.get(item.id, 0),
                "requested": equipment_requested.get(item.id, 0),
            }
        )
    groups = [
        {"category": category, "rows": rows}
        for category, rows in sorted(
            by_category.items(), key=lambda pair: (pair[0] is None, (pair[0] or "").lower())
        )
    ]

    ctx = base_admin_context(
        request, user, db, active_path="/bookings/catalogue",
        groups=groups,
        equipment_total=len(equipment),
        equipment_in_use=sum(1 for item in equipment if equipment_rooms.get(item.id)),
        service_rows=[
            {
                "service": service,
                "rooms": service_rooms.get(service.id, 0),
                "requested": service_requested.get(service.id, 0),
            }
            for service in services
        ],
        services_total=len(services),
        services_active=sum(1 for service in services if service.is_active),
    )
    return templates.TemplateResponse(request, "admin/bookings/catalogue.html", ctx)


# --------------------------------------------------------------------------
# One booking
# --------------------------------------------------------------------------


def _hours(start, end) -> float | int:
    """Duration in hours, without a decimal point it has not earned."""
    hours = round((to_app_tz(end) - to_app_tz(start)).total_seconds() / 3600, 1)
    return int(hours) if hours == int(hours) else hours


def insurance_state(booking: Booking, certificate: Document | None) -> str:
    """One of: ``on_file``, ``promised``, ``declined``, ``unasked``.

    Three answers and a document make four states, and telling them apart is
    the whole point of the card: "no certificate yet" and "told us they have
    no cover" are different problems with different responses.
    """
    if certificate is not None:
        return "on_file"
    answer = booking.request.liability_insurance if booking.request else None
    if answer is True:
        return "promised"
    if answer is False:
        return "declined"
    return "unasked"


@router.get("/bookings/{booking_id}", response_class=HTMLResponse)
def booking_detail(booking_id: int, request: Request, db: Session = Depends(get_db)):
    """The full picture of one booking.

    Also makes app/jobs/tasks.py's notification links real -- they have always
    pointed at /bookings/{id}, which until now was a 404.
    """
    user = get_authenticated_user(request, db)
    if not user:
        return RedirectResponse(url="/auth/login", status_code=303)

    booking = db.scalars(
        select(Booking)
        .options(
            joinedload(Booking.room),
            joinedload(Booking.party),
            joinedload(Booking.request),
            joinedload(Booking.created_by),
            joinedload(Booking.documents).joinedload(Document.uploaded_by),
            joinedload(Booking.equipment_requests).joinedload(BookingEquipmentRequest.equipment),
            joinedload(Booking.service_requests).joinedload(BookingServiceRequest.service),
        )
        .where(Booking.id == booking_id)
    ).unique().one_or_none()
    if booking is None:
        return RedirectResponse(url="/bookings", status_code=303)

    audit_entries = db.scalars(
        select(AuditLog)
        .where(AuditLog.entity_type == "booking", AuditLog.entity_id == booking.id)
        .order_by(AuditLog.id.desc())
        .limit(10)
    ).all()

    # Checked on load rather than only when Approve fails. Learning about a
    # clash from a 409 after deciding to approve is the wrong order.
    conflicts = find_conflicts(
        db,
        room_id=booking.room_id,
        start_at=booking.start_at,
        end_at=booking.end_at,
        source=booking.source,
        exclude_booking_id=booking.id,
    )

    documents = sorted(booking.documents, key=lambda row: row.uploaded_at, reverse=True)
    certificate = next(
        (row for row in documents if row.document_type == DocumentType.INSURANCE), None
    )

    # How much of the room this booking uses, for the header strip. Both halves
    # can be unset, and "25 of ?" says nothing, so it is all-or-nothing.
    capacity = booking.room.capacity if booking.room else None
    over_capacity = bool(
        capacity and booking.attendee_count and booking.attendee_count > capacity
    )

    ctx = base_admin_context(
        request, user, db, active_path="/bookings",
        booking=booking,
        booking_request=booking.request,
        audit_entries=list(audit_entries),
        conflicts=conflicts,
        documents=documents,
        certificate=certificate,
        insurance_state=insurance_state(booking, certificate),
        is_external=_is_external(booking),
        back_url=request.session.get("bookings_back", "/bookings"),
        capacity=capacity,
        over_capacity=over_capacity,
        duration_hours=_hours(booking.start_at, booking.end_at),
        now=app_now(),
    )
    return templates.TemplateResponse(request, "admin/bookings/detail.html", ctx)
