"""The bookings page: one page, two views, and a period you can change.

The list and the calendar used to be separate pages. They are two readings of
the same rows, so they are one page now -- and the list, which had a hard-coded
±30 day window and no filters at all, gained a period picker. An invisible
window is what makes a list look broken when it is merely narrow.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import select

from app.models.booking import Booking
from app.models.building import Building
from app.models.document import Document
from app.models.enums import (
    BookingSource,
    BookingStatus,
    DocumentType,
    OccupancyMode,
    PartyType,
)
from app.models.booking_request import BookingRequest
from app.models.floor import Floor
from app.models.party import Party
from app.models.room import Room

TZ = ZoneInfo("Europe/Berlin")


@pytest.fixture
def bookings(db_session):
    building = Building(name="Haus")
    db_session.add(building)
    db_session.flush()
    floor = Floor(building_id=building.id, name="EG", floor_number=0)
    db_session.add(floor)
    db_session.flush()
    room = Room(
        floor_id=floor.id, room_code="P-1", name="Grosser Saal", usage_type="event",
        occupancy_mode=OccupancyMode.BOOKABLE, public_bookable=True, bookable=True,
        capacity=40, cleaning_rate_daily=Decimal("45.00"),
    )
    party = Party(party_type=PartyType.EXTERNAL, name="Ada", email="ada@example.org")
    db_session.add_all([room, party])
    db_session.commit()

    today = datetime.now(TZ).replace(hour=10, minute=0, second=0, microsecond=0)
    rows = {
        # Tomorrow, so it is inside every window the picker offers.
        "soon": Booking(
            room_id=room.id, party_id=party.id, title="Morgen schon",
            start_at=today + timedelta(days=1), end_at=today + timedelta(days=1, hours=2),
            status=BookingStatus.PENDING, source=BookingSource.PUBLIC, attendee_count=25,
        ),
        # Outside ±30 days, so only the twelve-month window reaches it.
        "far": Booking(
            room_id=room.id, party_id=party.id, title="Weit weg",
            start_at=today + timedelta(days=90), end_at=today + timedelta(days=90, hours=2),
            status=BookingStatus.APPROVED, source=BookingSource.STAFF,
        ),
    }
    db_session.add_all(rows.values())
    db_session.commit()
    db_session.add(
        BookingRequest(
            booking_id=rows["soon"].id, public_ref="RB-TESTTEST",
            requester_first_name="Ada", requester_last_name="Lovelace",
            requester_email="ada@example.org",
        )
    )
    db_session.commit()
    return {"room": room, "party": party, **rows}


# --------------------------------------------------------------------------
# One page, two views
# --------------------------------------------------------------------------


def test_the_list_and_the_calendar_are_the_same_page(client, dev_login, bookings):
    dev_login(role="editor", email="e@example.org", display_name="Editor")
    assert client.get("/bookings").status_code == 200
    assert client.get("/bookings", params={"view": "calendar"}).status_code == 200


def test_each_view_links_to_the_other(client, dev_login, bookings):
    """The toggle is navigation, not a CSS switch: the calendar is a widget
    that measures its container, and a hidden container has no width."""
    dev_login(role="editor", email="e@example.org", display_name="Editor")
    assert 'href="/bookings?view=calendar"' in client.get("/bookings").text
    assert 'href="/bookings?view=list"' in client.get(
        "/bookings", params={"view": "calendar"}
    ).text


def test_an_unknown_view_falls_back_to_the_list(client, dev_login, bookings):
    dev_login(role="editor", email="e@example.org", display_name="Editor")
    response = client.get("/bookings", params={"view": "nonsense"})
    assert response.status_code == 200
    assert "Morgen schon" in response.text


# --------------------------------------------------------------------------
# The period
# --------------------------------------------------------------------------


def test_the_default_period_is_the_one_the_page_always_had(client, dev_login, bookings):
    dev_login(role="editor", email="e@example.org", display_name="Editor")
    text = client.get("/bookings").text
    assert "Morgen schon" in text
    assert "Weit weg" not in text


def test_a_wider_period_reaches_further(client, dev_login, bookings):
    dev_login(role="editor", email="e@example.org", display_name="Editor")
    text = client.get("/bookings", params={"range": "upcoming"}).text
    assert "Morgen schon" in text
    assert "Weit weg" in text


def test_a_custom_period_is_honoured(client, dev_login, bookings, db_session):
    """The period governs what has been decided.

    A request still waiting for an answer is owed one whatever window is on
    screen, so it stays -- a queue a filter can hide is a queue people stop
    trusting.
    """
    from app.models.enums import BookingStatus

    dev_login(role="editor", email="e@example.org", display_name="Editor")
    far = bookings["far"].start_at.astimezone(TZ).date()
    params = {"range": "custom", "from": far.isoformat(), "to": far.isoformat()}

    text = client.get("/bookings", params=params).text
    assert "Weit weg" in text
    assert "Morgen schon" in text, "a pending request is never filtered away"

    # Once it is decided, the window applies to it like anything else.
    bookings["soon"].status = BookingStatus.CANCELLED
    db_session.commit()
    assert "Morgen schon" not in client.get("/bookings", params=params).text


def test_an_unusable_custom_period_falls_back_rather_than_showing_nothing(
    client, dev_login, bookings
):
    """An end before its start, or junk, must not render an empty page with no
    explanation -- the reader would read that as "there are no bookings"."""
    dev_login(role="editor", email="e@example.org", display_name="Editor")
    for params in (
        {"range": "custom", "from": "2026-12-01", "to": "2026-01-01"},
        {"range": "custom", "from": "not-a-date", "to": "also-not"},
        {"range": "custom"},
    ):
        response = client.get("/bookings", params=params)
        assert response.status_code == 200, params
        assert "Morgen schon" in response.text, params


def test_the_window_is_named_on_the_page(client, dev_login, bookings):
    """So an empty list says what it looked at."""
    dev_login(role="editor", email="e@example.org", display_name="Editor")
    far = bookings["far"].start_at.astimezone(TZ).date()
    response = client.get(
        "/bookings",
        params={"range": "custom", "from": far.isoformat(), "to": far.isoformat()},
    )
    assert f"{far.day}." in response.text


def test_the_party_filter_narrows_the_list(client, dev_login, bookings, db_session):
    """State is grouped, not filtered; whose booking it is still is."""
    from app.models.enums import PartyType
    from app.models.party import Party

    colleague = Party(party_type=PartyType.PERSON, name="Jane", email="jane@example.org")
    db_session.add(colleague)
    db_session.flush()
    bookings["far"].party_id = colleague.id
    db_session.commit()

    dev_login(role="editor", email="e@example.org", display_name="Editor")

    external = client.get("/bookings", params={"range": "upcoming", "kind": "external"}).text
    assert "Morgen schon" in external and "Weit weg" not in external

    internal = client.get("/bookings", params={"range": "upcoming", "kind": "internal"}).text
    assert "Weit weg" in internal and "Morgen schon" not in internal


def test_a_junk_status_is_ignored_rather_than_fatal(client, dev_login, bookings):
    dev_login(role="editor", email="e@example.org", display_name="Editor")
    response = client.get("/bookings", params={"status": "banana"})
    assert response.status_code == 200
    assert "Morgen schon" in response.text


# --------------------------------------------------------------------------
# One booking
# --------------------------------------------------------------------------


def test_the_detail_page_reports_capacity_and_conflicts(client, dev_login, bookings):
    """Both are computed on load. Learning about a clash from a failing
    Approve is the wrong order to find out."""
    dev_login(role="editor", email="e@example.org", display_name="Editor")
    response = client.get(f"/bookings/{bookings['soon'].id}")
    assert response.status_code == 200
    assert "25" in response.text
    assert "40" in response.text


def test_a_clashing_approved_booking_shows_on_the_detail_page(
    client, dev_login, bookings, db_session
):
    clash = Booking(
        room_id=bookings["room"].id, party_id=bookings["party"].id, title="Belegt",
        start_at=bookings["soon"].start_at, end_at=bookings["soon"].end_at,
        status=BookingStatus.APPROVED, source=BookingSource.STAFF,
    )
    db_session.add(clash)
    db_session.commit()

    dev_login(role="editor", email="e@example.org", display_name="Editor")
    response = client.get(f"/bookings/{bookings['soon'].id}")
    assert f'href="/bookings/{clash.id}"' in response.text


def test_the_insurance_card_tells_the_four_states_apart(
    client, dev_login, bookings, db_session
):
    dev_login(role="editor", email="e@example.org", display_name="Editor")
    booking_id = bookings["soon"].id
    request_row = db_session.scalars(
        select(BookingRequest).where(BookingRequest.booking_id == booking_id)
    ).one()

    def state() -> str:
        text = client.get(f"/bookings/{booking_id}").text
        return re.search(r'data-insurance-state="([a-z_]+)"', text).group(1)

    # Never asked -- which is what NULL means, and is not "no cover".
    assert state() == "unasked"

    request_row.liability_insurance = False
    db_session.commit()
    assert state() == "declined"

    request_row.liability_insurance = True
    db_session.commit()
    assert state() == "promised"

    db_session.add(
        Document(
            booking_id=booking_id, document_type=DocumentType.INSURANCE,
            title="Cover", object_key="documents/insurance/x.pdf",
            original_filename="cover.pdf", mime_type="application/pdf",
            uploaded_at=datetime.now(TZ),
        )
    )
    db_session.commit()
    assert state() == "on_file"


def test_the_bookings_page_comes_back_to_the_view_you_left(client, dev_login):
    """Open a booking from the calendar, come back, still the calendar.

    The back link and the sidebar both point at a bare /bookings, so the page
    has to remember rather than the links having to carry it.
    """
    dev_login(role="admin", email="a@example.org", display_name="Admin")
    calendar_marker = 'id="calendar-legend"'

    assert calendar_marker in client.get("/bookings?view=calendar").text

    # No ?view= -- what the back link and the sidebar entry both send.
    back = client.get("/bookings")
    assert back.status_code == 200
    assert calendar_marker in back.text

    # Asking for the list explicitly still wins, and is remembered in turn.
    assert calendar_marker not in client.get("/bookings?view=list").text
    assert calendar_marker not in client.get("/bookings").text


def test_the_list_separates_external_from_internal(
    client, dev_login, db_session
):
    """Two workflows on one page would need one table to serve both.

    What decides is the party the booking is FOR -- a request typed in by
    staff for an outside organisation is external, whatever door it came
    through.
    """
    from datetime import datetime, timedelta
    from zoneinfo import ZoneInfo

    from app.models.booking import Booking
    from app.models.building import Building
    from app.models.enums import BookingSource, BookingStatus, OccupancyMode, PartyType
    from app.models.floor import Floor
    from app.models.party import Party
    from app.models.room import Room

    building = Building(name="Haus")
    db_session.add(building)
    db_session.flush()
    floor = Floor(building_id=building.id, name="EG", floor_number=0)
    db_session.add(floor)
    db_session.flush()
    room = Room(
        floor_id=floor.id, room_code="R-9", name="Saal", usage_type="event",
        occupancy_mode=OccupancyMode.BOOKABLE, bookable=True,
    )
    outsider = Party(party_type=PartyType.EXTERNAL, name="Kollektiv", email="k@example.org")
    colleague = Party(party_type=PartyType.PERSON, name="Jane Miller", email="j@example.org")
    db_session.add_all([room, outsider, colleague])
    db_session.flush()

    start = datetime.now(ZoneInfo("Europe/Berlin")) + timedelta(days=9)
    db_session.add_all([
        # Entered by staff, but for an outside party: external.
        Booking(
            room_id=room.id, party_id=outsider.id, title="Lesung",
            start_at=start, end_at=start + timedelta(hours=2),
            status=BookingStatus.PENDING, source=BookingSource.STAFF,
        ),
        Booking(
            room_id=room.id, party_id=colleague.id, title="Redaktionssitzung",
            start_at=start + timedelta(days=1), end_at=start + timedelta(days=1, hours=2),
            status=BookingStatus.PENDING, source=BookingSource.INTERNAL,
        ),
    ])
    db_session.commit()

    dev_login(role="admin", email="a@example.org", display_name="Admin")

    both = client.get("/bookings")
    assert both.status_code == 200
    assert "Lesung" in both.text and "Redaktionssitzung" in both.text

    external = client.get("/bookings?kind=external").text
    assert "Lesung" in external and "Redaktionssitzung" not in external

    internal = client.get("/bookings?kind=internal").text
    assert "Redaktionssitzung" in internal and "Lesung" not in internal


def test_the_old_requests_address_still_leads_somewhere(client, dev_login):
    """It was its own page for a day. Links and bookmarks outlive that."""
    dev_login(role="admin", email="a@example.org", display_name="Admin")
    response = client.get("/bookings/requests", follow_redirects=False)
    assert response.status_code == 307
    assert response.headers["location"] == "/bookings"
    assert client.get("/bookings/requests?kind=external", follow_redirects=False).headers[
        "location"
    ] == "/bookings?kind=external"


def test_a_member_cannot_reach_the_booking_list(client, dev_login):
    dev_login(role="member", email="m@example.org", display_name="Member")
    response = client.get("/bookings", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/portal"


def test_back_from_a_booking_returns_to_the_list_it_was_opened_from(
    client, dev_login, db_session
):
    """Including its filters: a decision made from the requests inbox should
    land back in the queue, not at the top of every booking."""
    from datetime import datetime, timedelta
    from zoneinfo import ZoneInfo

    from app.models.booking import Booking
    from app.models.building import Building
    from app.models.enums import BookingSource, BookingStatus, OccupancyMode, PartyType
    from app.models.floor import Floor
    from app.models.party import Party
    from app.models.room import Room

    building = Building(name="Haus")
    db_session.add(building)
    db_session.flush()
    floor = Floor(building_id=building.id, name="EG", floor_number=0)
    db_session.add(floor)
    db_session.flush()
    room = Room(
        floor_id=floor.id, room_code="R-8", name="Saal", usage_type="event",
        occupancy_mode=OccupancyMode.BOOKABLE, bookable=True,
    )
    party = Party(party_type=PartyType.EXTERNAL, name="Kollektiv", email="k2@example.org")
    db_session.add_all([room, party])
    db_session.flush()
    start = datetime.now(ZoneInfo("Europe/Berlin")) + timedelta(days=6)
    booking = Booking(
        room_id=room.id, party_id=party.id, title="Lesung",
        start_at=start, end_at=start + timedelta(hours=2),
        status=BookingStatus.PENDING, source=BookingSource.PUBLIC,
    )
    db_session.add(booking)
    db_session.commit()

    dev_login(role="admin", email="a@example.org", display_name="Admin")

    client.get("/bookings?kind=external&range=upcoming")
    detail = client.get(f"/bookings/{booking.id}")
    assert 'href="/bookings?kind=external&amp;range=upcoming"' in detail.text

    client.get("/bookings?view=calendar")
    assert 'href="/bookings?view=calendar"' in client.get(f"/bookings/{booking.id}").text
