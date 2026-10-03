"""The booking calendar, on all three surfaces.

The reference app's calendar published every booking's event title and room to
anyone on the internet under open CORS. The disclosure rule here follows the
availability API: the public and member calendars say a room is busy and
nothing more.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import select

from app.models.booking import Booking
from app.models.building import Building
from app.models.enums import BookingSource, BookingStatus, OccupancyMode, PartyType
from app.models.floor import Floor
from app.models.party import Party
from app.models.room import Room
from app.services.calendar import build_month, resolve_month

TZ = ZoneInfo("Europe/Berlin")


@pytest.fixture
def seeded(db_session):
    building = Building(name="Haus")
    db_session.add(building)
    db_session.flush()
    floor = Floor(building_id=building.id, name="EG", floor_number=0)
    db_session.add(floor)
    db_session.flush()
    public = Room(
        floor_id=floor.id, room_code="P-1", name="Grosser Saal", usage_type="event",
        occupancy_mode=OccupancyMode.BOOKABLE, public_bookable=True, bookable=True,
        cleaning_rate_daily=Decimal("45.00"),
    )
    private = Room(
        floor_id=floor.id, room_code="I-1", name="Hinterzimmer", usage_type="office",
        occupancy_mode=OccupancyMode.INTERNAL, bookable=True, public_bookable=False,
    )
    party = Party(party_type=PartyType.EXTERNAL, name="Ada", email="ada@example.org")
    db_session.add_all([public, private, party])
    db_session.commit()

    start = datetime.now(TZ).replace(hour=10, minute=0, second=0, microsecond=0) + timedelta(days=3)
    approved = Booking(
        room_id=public.id, party_id=party.id, title="Nachbarschaftstreffen",
        start_at=start, end_at=start + timedelta(hours=3),
        status=BookingStatus.APPROVED, source=BookingSource.PUBLIC,
    )
    pending = Booking(
        room_id=public.id, party_id=party.id, title="Noch nicht entschieden",
        start_at=start + timedelta(days=1), end_at=start + timedelta(days=1, hours=2),
        status=BookingStatus.PENDING, source=BookingSource.PUBLIC,
    )
    secret = Booking(
        room_id=private.id, party_id=party.id, title="Internes Meeting",
        start_at=start, end_at=start + timedelta(hours=1),
        status=BookingStatus.APPROVED, source=BookingSource.INTERNAL,
    )
    db_session.add_all([approved, pending, secret])
    db_session.commit()
    return {"public": public, "private": private, "start": start}


def test_resolve_month_never_raises_on_junk(seeded=None):
    now_year, now_month = resolve_month(None, None)
    assert 1 <= now_month <= 12
    assert resolve_month(2030, 13) == (now_year, now_month)
    assert resolve_month(2030, 0) == (now_year, now_month)
    assert resolve_month(99999, 6) == (now_year, now_month)
    assert resolve_month(2030, 6) == (2030, 6)


def test_public_calendar_shows_busy_but_never_the_title(client, seeded):
    response = client.get("/book/calendar")
    assert response.status_code == 200
    assert "Grosser Saal" in response.text
    # The event title is the thing the reference app leaked.
    assert "Nachbarschaftstreffen" not in response.text
    # Internal rooms are not on the public calendar at all.
    assert "Hinterzimmer" not in response.text
    assert "Internes Meeting" not in response.text


def test_public_calendar_shows_only_confirmed_bookings(client, seeded, db_session):
    """A pending request is not an occupancy -- showing it would tell the
    public a room is taken when it may yet be refused."""
    grid = build_month(
        db_session,
        year=seeded["start"].year,
        month=seeded["start"].month,
        rooms=[seeded["public"]],
        include_titles=False,
    )
    entries = [e for week in grid.weeks for day in week for e in day.entries]
    assert entries, "expected the approved booking"
    assert all(entry.status == "approved" for entry in entries)


def test_admin_calendar_shows_titles_and_pending(client, dev_login, seeded):
    dev_login(role="editor", email="e@example.org", display_name="Editor")
    response = client.get("/bookings/calendar")
    assert response.status_code == 200
    assert "Nachbarschaftstreffen" in response.text
    assert "Noch nicht entschieden" in response.text
    assert "Internes Meeting" in response.text


def test_admin_calendar_entries_link_to_the_booking(client, dev_login, seeded, db_session):
    dev_login(role="editor", email="e@example.org", display_name="Editor")
    booking = db_session.scalars(
        select(Booking).where(Booking.title == "Nachbarschaftstreffen")
    ).one()
    response = client.get("/bookings/calendar")
    assert f'href="/bookings/{booking.id}"' in response.text


def test_calendar_path_is_not_read_as_a_booking_id(client, dev_login, seeded):
    """/bookings/calendar must not be matched by /bookings/{booking_id}.

    The calendar now lives at /bookings?view=calendar, but the old address is
    kept: notification rows, emails and bookmarks point at it. It must land on
    the calendar, not fall through to the numeric-id route -- which would send
    it to the bookings list and quietly lose the destination.
    """
    dev_login(role="editor", email="e@example.org", display_name="Editor")
    response = client.get("/bookings/calendar", follow_redirects=False)
    assert response.status_code == 307
    assert response.headers["location"] == "/bookings?view=calendar"
    assert client.get("/bookings/calendar").status_code == 200


def test_member_calendar_hides_titles(client, dev_login, db_session, seeded):
    dev_login(role="member", email="m@example.org", display_name="Member")
    response = client.get("/portal/calendar")
    assert response.status_code == 200
    assert "Hinterzimmer" in response.text
    assert "Internes Meeting" not in response.text


def test_month_navigation_works_without_javascript(client, seeded):
    """Prev/next are plain links, so the calendar needs no library at all."""
    page = client.get("/book/calendar")
    assert 'href="/book/calendar?year=' in page.text
    year, month = seeded["start"].year, seeded["start"].month
    following = client.get("/book/calendar", params={"year": year, "month": month})
    assert following.status_code == 200


def test_multi_day_booking_appears_on_every_day_it_covers(db_session, seeded):
    start = seeded["start"].replace(hour=9)
    db_session.add(
        Booking(
            room_id=seeded["public"].id,
            party_id=db_session.scalars(select(Party)).first().id,
            title="Lange Veranstaltung",
            start_at=start, end_at=start + timedelta(days=2, hours=4),
            status=BookingStatus.APPROVED, source=BookingSource.STAFF,
        )
    )
    db_session.commit()
    grid = build_month(
        db_session, year=start.year, month=start.month, rooms=[seeded["public"]],
        include_titles=True,
    )
    days = [
        day.day for week in grid.weeks for day in week
        if any(e.title == "Lange Veranstaltung" for e in day.entries)
    ]
    assert len(days) == 3, f"expected three days, got {days}"


def test_booking_ending_at_midnight_does_not_bleed_into_the_next_day(db_session, seeded):
    """The same half-open rule the conflict check uses, so the calendar and
    the availability logic never disagree about which days are busy."""
    start = seeded["start"].replace(hour=0, minute=0)
    db_session.add(
        Booking(
            room_id=seeded["public"].id,
            party_id=db_session.scalars(select(Party)).first().id,
            title="Ganztag",
            start_at=start, end_at=start + timedelta(days=1),
            status=BookingStatus.APPROVED, source=BookingSource.STAFF,
        )
    )
    db_session.commit()
    grid = build_month(
        db_session, year=start.year, month=start.month, rooms=[seeded["public"]],
        include_titles=True,
    )
    days = [
        day.day for week in grid.weeks for day in week
        if any(e.title == "Ganztag" for e in day.entries)
    ]
    assert len(days) == 1, f"a midnight-to-midnight booking covers one day, got {days}"


def test_calendar_loads_nothing_from_a_third_party(client, seeded):
    """The reference app pulled Syncfusion from a CDN on this page."""
    import re
    from urllib.parse import urlparse

    page = client.get("/book/calendar")
    # Only resources the browser fetches before paint count -- a <link>
    # stylesheet or any src. Navigational <a href> (e.g. the footer's legally
    # required Impressum/Datenschutz links to the org site) does not leak an IP.
    resource_urls = re.findall(
        r'<link\b[^>]*\bhref="(https?://[^"]+)"', page.text
    ) + re.findall(r'\bsrc="(https?://[^"]+)"', page.text)
    hosts = {urlparse(url).hostname for url in resource_urls}
    assert not {h for h in hosts if h not in {"testserver", None}}


def test_every_booking_on_a_busy_day_is_reachable(client, dev_login, db_session, seeded):
    """A plain "+3 more" count is a dead end: there is no day view to click
    through to, so the fourth booking on a busy day was unreachable."""
    party = db_session.scalars(select(Party)).first()
    start = seeded["start"]
    for index in range(5):
        db_session.add(
            Booking(
                room_id=seeded["public"].id, party_id=party.id,
                title=f"Termin {index}",
                start_at=start + timedelta(hours=index),
                end_at=start + timedelta(hours=index, minutes=30),
                status=BookingStatus.APPROVED, source=BookingSource.STAFF,
            )
        )
    db_session.commit()

    dev_login(role="editor", email="e@example.org", display_name="Editor")
    page = client.get(
        "/bookings/calendar", params={"year": start.year, "month": start.month}
    )
    assert page.status_code == 200
    for index in range(5):
        assert f"Termin {index}" in page.text, f"Termin {index} is not reachable"
    # Disclosed with <details>, so it needs no JavaScript and no extra route.
    assert "<details" in page.text


# --------------------------------------------------------------------------
# The interactive admin calendar
# --------------------------------------------------------------------------


def test_calendar_feed_carries_what_staff_need(client, dev_login, seeded):
    dev_login(role="editor", email="e@example.org", display_name="Editor")
    start = seeded["start"]
    response = client.get(
        "/api/v1/bookings/calendar-events",
        params={
            "start": (start - timedelta(days=2)).isoformat(),
            "end": (start + timedelta(days=5)).isoformat(),
        },
    )
    assert response.status_code == 200
    events = response.json()
    titles = {event["title"] for event in events}
    assert "Nachbarschaftstreffen" in titles
    # Rooms-as-lanes needs the resource id on every event.
    assert all(event["resourceIds"] for event in events)
    sample = next(e for e in events if e["title"] == "Nachbarschaftstreffen")
    assert sample["extendedProps"]["status"] == "approved"
    assert sample["extendedProps"]["room"] == "Grosser Saal"


def test_calendar_feed_excludes_cancelled_bookings(client, dev_login, seeded, db_session):
    """A cancelled booking occupies nothing; showing it makes a free room look busy."""
    booking = db_session.scalars(
        select(Booking).where(Booking.title == "Nachbarschaftstreffen")
    ).one()
    booking.status = BookingStatus.CANCELLED
    db_session.commit()

    dev_login(role="editor", email="e@example.org", display_name="Editor")
    start = seeded["start"]
    events = client.get(
        "/api/v1/bookings/calendar-events",
        params={"start": (start - timedelta(days=2)).isoformat(),
                "end": (start + timedelta(days=5)).isoformat()},
    ).json()
    assert "Nachbarschaftstreffen" not in {e["title"] for e in events}


def test_calendar_feed_refuses_an_absurd_range(client, dev_login, seeded):
    dev_login(role="editor", email="e@example.org", display_name="Editor")
    start = seeded["start"]
    assert client.get(
        "/api/v1/bookings/calendar-events",
        params={"start": start.isoformat(), "end": (start + timedelta(days=900)).isoformat()},
    ).status_code == 400
    assert client.get(
        "/api/v1/bookings/calendar-events",
        params={"start": start.isoformat(), "end": (start - timedelta(days=1)).isoformat()},
    ).status_code == 400


def test_calendar_feed_is_staff_only(client, dev_login, seeded):
    """Titles and party names must not reach a member."""
    dev_login(role="member", email="m@example.org", display_name="Member")
    start = seeded["start"]
    response = client.get(
        "/api/v1/bookings/calendar-events",
        params={"start": start.isoformat(), "end": (start + timedelta(days=1)).isoformat()},
    )
    assert response.status_code == 403


def test_resources_feed_lists_rooms(client, dev_login, seeded):
    dev_login(role="editor", email="e@example.org", display_name="Editor")
    resources = client.get("/api/v1/bookings/calendar-resources").json()
    assert {r["title"] for r in resources} == {"Grosser Saal", "Hinterzimmer"}


def test_dragging_a_booking_moves_it(client, dev_login, seeded, db_session):
    csrf = dev_login(role="editor", email="e@example.org", display_name="Editor")
    booking = db_session.scalars(
        select(Booking).where(Booking.title == "Nachbarschaftstreffen")
    ).one()
    new_start = seeded["start"] + timedelta(days=2)

    response = client.patch(
        f"/api/v1/bookings/{booking.id}",
        json={
            "start_at": new_start.isoformat(),
            "end_at": (new_start + timedelta(hours=3)).isoformat(),
        },
        headers={"x-csrf-token": csrf},
    )
    assert response.status_code == 200
    db_session.refresh(booking)
    assert booking.start_at.day == new_start.day


def test_dragging_between_room_lanes_changes_the_room(client, dev_login, seeded, db_session):
    """Without room_id on BookingUpdate this silently did nothing."""
    csrf = dev_login(role="editor", email="e@example.org", display_name="Editor")
    booking = db_session.scalars(
        select(Booking).where(Booking.title == "Internes Meeting")
    ).one()
    assert booking.room_id == seeded["private"].id

    # A lane drag moves the booking in time as well as across rooms; the
    # target room is busy at the original time.
    free = seeded["start"] + timedelta(days=6)
    response = client.patch(
        f"/api/v1/bookings/{booking.id}",
        json={
            "room_id": seeded["public"].id,
            "start_at": free.isoformat(),
            "end_at": (free + timedelta(hours=1)).isoformat(),
        },
        headers={"x-csrf-token": csrf},
    )
    assert response.status_code == 200, response.text
    db_session.refresh(booking)
    assert booking.room_id == seeded["public"].id


def test_a_public_booking_cannot_be_dragged_into_a_private_room(
    client, dev_login, seeded, db_session
):
    """The customer asked for a room the public can book. Moving their booking
    somewhere the public cannot book is not a reschedule, it is a different
    agreement."""
    csrf = dev_login(role="editor", email="e@example.org", display_name="Editor")
    booking = db_session.scalars(
        select(Booking).where(Booking.title == "Nachbarschaftstreffen")
    ).one()
    original = booking.room_id

    response = client.patch(
        f"/api/v1/bookings/{booking.id}",
        json={"room_id": seeded["private"].id},
        headers={"x-csrf-token": csrf},
    )
    assert response.status_code == 400
    assert "publicly bookable" in response.json()["detail"]

    db_session.refresh(booking)
    assert booking.room_id == original


def test_dragging_onto_a_clash_is_refused(client, dev_login, seeded, db_session):
    """The server re-checks on every move, so the UI can snap the booking back."""
    csrf = dev_login(role="editor", email="e@example.org", display_name="Editor")
    party = db_session.scalars(select(Party)).first()
    blocker_start = seeded["start"] + timedelta(days=4)
    db_session.add(
        Booking(
            room_id=seeded["public"].id, party_id=party.id, title="Blockiert",
            start_at=blocker_start, end_at=blocker_start + timedelta(hours=4),
            status=BookingStatus.APPROVED, source=BookingSource.STAFF,
        )
    )
    db_session.commit()

    booking = db_session.scalars(
        select(Booking).where(Booking.title == "Nachbarschaftstreffen")
    ).one()
    original = booking.start_at

    response = client.patch(
        f"/api/v1/bookings/{booking.id}",
        json={
            "start_at": (blocker_start + timedelta(hours=1)).isoformat(),
            "end_at": (blocker_start + timedelta(hours=2)).isoformat(),
        },
        headers={"x-csrf-token": csrf},
    )
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "room_unavailable"

    db_session.refresh(booking)
    assert booking.start_at == original, "a refused move must not have been applied"


def test_admin_calendar_page_self_hosts_its_library(client, dev_login, seeded):
    """The old calendar pulled Syncfusion from a CDN -- 3.48 MB, unversioned."""
    import re
    from urllib.parse import urlparse

    dev_login(role="editor", email="e@example.org", display_name="Editor")
    page = client.get("/bookings/calendar")
    assert page.status_code == 200
    assert "/static/vendor/event-calendar/event-calendar.min.js" in page.text

    hosts = {
        urlparse(url).hostname
        for url in re.findall(r'(?:href|src)="(https?://[^"]+)"', page.text)
    }
    assert not {h for h in hosts if h not in {"testserver", None}}

    for path in (
        "/static/vendor/event-calendar/event-calendar.min.js",
        "/static/vendor/event-calendar/event-calendar.min.css",
    ):
        assert client.get(path).status_code == 200, f"{path} was not vendored"


def test_admin_calendar_still_works_without_javascript(client, dev_login, seeded):
    """The server-rendered grid stands in, so the page is never blank."""
    dev_login(role="editor", email="e@example.org", display_name="Editor")
    page = client.get(
        "/bookings/calendar",
        params={"year": seeded["start"].year, "month": seeded["start"].month},
    )
    assert "<noscript>" in page.text
    noscript = page.text.split("<noscript>")[1].split("</noscript>")[0]
    assert "Nachbarschaftstreffen" in noscript
