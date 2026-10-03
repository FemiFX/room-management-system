from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.core.config import get_settings


def app_timezone() -> ZoneInfo:
    tz_name = get_settings().default_timezone
    try:
        return ZoneInfo(tz_name)
    except ZoneInfoNotFoundError:  # pragma: no cover
        return ZoneInfo("Europe/Berlin")


def app_now() -> datetime:
    return datetime.now(app_timezone())


def to_app_tz(value: datetime) -> datetime:
    """Return ``value`` in the application timezone.

    A naive datetime is *assumed* to already be local rather than UTC. That
    matters more than it looks: SQLite discards timezone information, so rows
    written as aware come back naive, and treating them as UTC would shift
    every comparison and day count by the local offset. A booking ending
    00:30 Berlin is 23:30 UTC the previous day -- counting cleaning days in
    UTC would bill the wrong number.
    """
    tz = app_timezone()
    if value.tzinfo is None:
        return value.replace(tzinfo=tz)
    return value.astimezone(tz)

