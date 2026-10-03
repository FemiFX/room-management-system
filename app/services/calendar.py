"""Month-grid calendar data.

Server-rendered rather than handed to a JavaScript calendar library. Two
reasons: the reference app pulled Syncfusion from a CDN, which is exactly the
third-party dependency we removed from the public page for privacy; and a
booking calendar is a table of days, which HTML already does well. Prev/next
are ordinary links, so the whole thing works with JavaScript disabled.

Callers decide what each audience may see -- this module only shapes the grid.
"""

from __future__ import annotations

import calendar as _calendar
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.core.time_utils import app_now, app_timezone, to_app_tz
from app.models.booking import Booking
from app.models.enums import BookingStatus
from app.models.room import Room

#: Monday-first, matching German convention.
_FIRST_WEEKDAY = 0


@dataclass
class CalendarEntry:
    booking_id: int
    room_id: int
    room_name: str
    start_at: datetime
    end_at: datetime
    status: str
    source: str
    #: None on surfaces that must not disclose what a booking is for.
    title: str | None = None
    whole_day: bool = False

    @property
    def start_label(self) -> str:
        return to_app_tz(self.start_at).strftime("%H:%M")

    @property
    def end_label(self) -> str:
        return to_app_tz(self.end_at).strftime("%H:%M")


@dataclass
class CalendarDay:
    day: date
    in_month: bool
    is_today: bool
    entries: list[CalendarEntry] = field(default_factory=list)


@dataclass
class CalendarMonth:
    year: int
    month: int
    weeks: list[list[CalendarDay]]
    rooms: list[Room]

    @property
    def label(self) -> str:
        return date(self.year, self.month, 1).strftime("%B %Y")

    @property
    def previous(self) -> tuple[int, int]:
        first = date(self.year, self.month, 1) - timedelta(days=1)
        return first.year, first.month

    @property
    def next(self) -> tuple[int, int]:
        last = date(self.year, self.month, _calendar.monthrange(self.year, self.month)[1])
        following = last + timedelta(days=1)
        return following.year, following.month


def resolve_month(year: int | None, month: int | None) -> tuple[int, int]:
    """Clamp a requested month to something sane. Never raises on junk input."""
    now = app_now()
    if not year or not month or not (1 <= month <= 12) or not (1970 <= year <= 2200):
        return now.year, now.month
    return year, month


def build_month(
    db: Session,
    *,
    year: int,
    month: int,
    rooms: list[Room],
    statuses: set[BookingStatus] | None = None,
    include_titles: bool = False,
) -> CalendarMonth:
    """Bookings for one month, laid out as weeks of days.

    ``include_titles`` is the disclosure switch: the public and member
    calendars pass False, so an event title never reaches an audience that has
    no business reading it. The admin calendar passes True.
    """
    statuses = statuses or {BookingStatus.APPROVED}
    room_ids = [room.id for room in rooms]

    tz = app_timezone()
    grid_start = date(year, month, 1)
    grid_end = date(year, month, _calendar.monthrange(year, month)[1])
    # Widen to the whole displayed grid, so a booking in a leading or trailing
    # cell from an adjacent month is not silently dropped.
    window_start = datetime.combine(
        grid_start - timedelta(days=7), datetime.min.time(), tzinfo=tz
    )
    window_end = datetime.combine(grid_end + timedelta(days=8), datetime.min.time(), tzinfo=tz)

    entries: list[CalendarEntry] = []
    if room_ids:
        rows = db.scalars(
            select(Booking)
            .options(joinedload(Booking.room), joinedload(Booking.request))
            .where(
                Booking.room_id.in_(room_ids),
                Booking.status.in_(list(statuses)),
                Booking.start_at < window_end,
                Booking.end_at > window_start,
            )
            .order_by(Booking.start_at.asc())
        ).unique().all()
        for row in rows:
            entries.append(
                CalendarEntry(
                    booking_id=row.id,
                    room_id=row.room_id,
                    room_name=row.room.name if row.room else "",
                    start_at=row.start_at,
                    end_at=row.end_at,
                    status=row.status.value,
                    source=row.source.value,
                    title=row.title if include_titles else None,
                    whole_day=bool(row.request.whole_day) if row.request else False,
                )
            )

    today = app_now().date()
    weeks: list[list[CalendarDay]] = []
    for week in _calendar.Calendar(firstweekday=_FIRST_WEEKDAY).monthdatescalendar(year, month):
        row: list[CalendarDay] = []
        for day in week:
            row.append(
                CalendarDay(
                    day=day,
                    in_month=day.month == month,
                    is_today=day == today,
                    entries=[entry for entry in entries if _touches(entry, day)],
                )
            )
        weeks.append(row)

    return CalendarMonth(year=year, month=month, weeks=weeks, rooms=rooms)


def _touches(entry: CalendarEntry, day: date) -> bool:
    """Does a half-open booking interval overlap this calendar day?

    A booking ending exactly at midnight does not reach into the next day --
    the same half-open rule the conflict check uses, so the calendar and the
    availability logic never disagree about which days are busy.
    """
    start = to_app_tz(entry.start_at)
    end = to_app_tz(entry.end_at)
    end_day = end.date()
    if end.time() == datetime.min.time() and end_day > start.date():
        end_day -= timedelta(days=1)
    return start.date() <= day <= end_day
