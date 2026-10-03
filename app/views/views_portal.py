"""Member-facing booking portal.

Deliberately does NOT use base_admin_context or admin/layout.html -- those
build the admin sidebar and dereference staff-only attributes. The portal is a
separate, much smaller surface reached only by Role.MEMBER (and by staff, who
may open it to support a member).

Pages are server-rendered shells; the booking itself goes through
/api/v1/portal/* from page JS, which is the convention the admin UI already
uses (see app/static/js/crud.js).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import joinedload

from app.core.config import get_settings
from app.core.i18n import get_supported_languages, language_display_name, resolve_language
from app.core.security import generate_csrf_token
from app.core.templating import templates
from app.core.time_utils import app_now, to_app_tz
from app.db.session import get_db
from app.models.booking import Booking
from app.models.enums import BookingStatus, OccupancyMode
from app.models.equipment import RoomEquipment
from app.models.room import Room
from app.services.calendar import build_month, resolve_month
from app.views.deps import get_authenticated_user

router = APIRouter()


def portal_context(request, user, active_path: str, **kwargs) -> dict:
    """The portal's own context. No nav_sections, no notifications, no admin."""
    csrf_token = request.session.setdefault("csrf_token", generate_csrf_token())
    current_language = resolve_language(request, user=user)
    return {
        "request": request,
        "csrf_token": csrf_token,
        "current_user": user,
        "current_language": current_language,
        "supported_languages": get_supported_languages(),
        "language_options": [
            {"code": code, "label": language_display_name(code)} for code in get_supported_languages()
        ],
        "user_name": user.display_name,
        "user_initials": "".join(p[0].upper() for p in user.display_name.split()[:2]) or "U",
        "active_path": active_path,
        **kwargs,
    }


def _member_bookings(db: Session, user) -> list[Booking]:
    """The member's own bookings, newest first."""
    condition = Booking.created_by_user_id == user.id
    if user.party_id is not None:
        condition = condition | (Booking.party_id == user.party_id)
    return list(
        db.scalars(
            select(Booking)
            .options(joinedload(Booking.room))
            .where(condition)
            .order_by(Booking.start_at.desc())
        ).unique().all()
    )


def _bookable_rooms(db: Session) -> list[Room]:
    return list(
        db.scalars(
            select(Room)
            .where(
                Room.is_active.is_(True),
                (Room.bookable.is_(True)) | (Room.occupancy_mode == OccupancyMode.MIXED),
            )
            .options(joinedload(Room.room_equipment).joinedload(RoomEquipment.equipment))
            .order_by(Room.name.asc())
        ).unique().all()
    )


@router.get("/portal", response_class=HTMLResponse)
def portal_home(request: Request, db: Session = Depends(get_db)):
    user = get_authenticated_user(request, db)
    if not user:
        return RedirectResponse(url="/auth/login", status_code=303)

    now = app_now()
    upcoming = [
        booking
        for booking in _member_bookings(db, user)
        if to_app_tz(booking.end_at) >= now and booking.status == BookingStatus.APPROVED
    ][:5]
    ctx = portal_context(
        request, user, active_path="/portal",
        upcoming=list(reversed(upcoming)),
        linked=user.party_id is not None,
    )
    return templates.TemplateResponse(request, "portal/home.html", ctx)


@router.get("/portal/book", response_class=HTMLResponse)
def portal_book(request: Request, db: Session = Depends(get_db)):
    user = get_authenticated_user(request, db)
    if not user:
        return RedirectResponse(url="/auth/login", status_code=303)

    settings = get_settings()
    ctx = portal_context(
        request, user, active_path="/portal/book",
        rooms=_bookable_rooms(db),
        linked=user.party_id is not None,
        min_date=app_now().date().isoformat(),
        max_date=(app_now() + timedelta(days=settings.member_booking_max_horizon_days)).date().isoformat(),
        max_hours=settings.member_booking_max_duration_hours,
    )
    return templates.TemplateResponse(request, "portal/book.html", ctx)


@router.get("/portal/bookings", response_class=HTMLResponse)
def portal_bookings(request: Request, db: Session = Depends(get_db)):
    user = get_authenticated_user(request, db)
    if not user:
        return RedirectResponse(url="/auth/login", status_code=303)

    ctx = portal_context(
        request, user, active_path="/portal/bookings",
        bookings=_member_bookings(db, user),
        now=app_now(),
    )
    return templates.TemplateResponse(request, "portal/bookings.html", ctx)


@router.get("/portal/calendar", response_class=HTMLResponse)
def portal_calendar(
    request: Request,
    year: int | None = None,
    month: int | None = None,
    db: Session = Depends(get_db),
):
    """Internal availability. Intervals only -- a member has no business
    knowing who booked a room or what for."""
    user = get_authenticated_user(request, db)
    if not user:
        return RedirectResponse(url="/auth/login", status_code=303)

    year, month = resolve_month(year, month)
    grid = build_month(
        db, year=year, month=month, rooms=_bookable_rooms(db), include_titles=False
    )
    ctx = portal_context(request, user, active_path="/portal/calendar", month=grid)
    return templates.TemplateResponse(request, "portal/calendar.html", ctx)
