"""The public booking surface.

Several tests here name a specific defect in the Flask app this replaces. That
app is the reference for behaviour, not for security: it authorised nothing on
its modify route, trusted a browser-computed price, and answered differently
for known and unknown booking numbers.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import select

from app.models.booking import Booking
from app.models.booking_request import BookingRequest
from app.models.building import Building
from app.models.enums import BookingSource, BookingStatus, OccupancyMode, PartyType
from app.models.equipment import Equipment, RoomEquipment
from app.models.floor import Floor
from app.models.party import Party
from app.models.room import Room
from app.models.enums import DocumentType
from app.services.booking_tokens import make_manage_token
from app.services.rate_limit import reset_fallback

TZ = ZoneInfo("Europe/Berlin")


def _reset_rate_limiter():
    """Both halves of the limiter, not just the in-process one.

    ``reset_fallback`` clears the counters used when Redis is unreachable. On
    a machine where the dev stack publishes Redis, the limiter uses THAT --
    and its fixed windows are an hour long, so the counters outlive the test
    that made them and every later submission answers 429.
    """
    reset_fallback()
    try:
        from app.integrations.redis_client import get_redis_client

        client = get_redis_client()
        keys = list(client.scan_iter("rl:*"))
        if keys:
            client.delete(*keys)
    except Exception:
        pass  # No Redis here: the in-process counters were the whole story.


@pytest.fixture(autouse=True)
def _clean_rate_limiter():
    _reset_rate_limiter()
    yield
    _reset_rate_limiter()


@pytest.fixture
def rooms(db_session):
    building = Building(name="Main")
    db_session.add(building)
    db_session.flush()
    floor = Floor(building_id=building.id, name="G", floor_number=0)
    db_session.add(floor)
    db_session.flush()
    public = Room(
        floor_id=floor.id, room_code="P-1", name="Main Hall", usage_type="event",
        occupancy_mode=OccupancyMode.BOOKABLE, bookable=False, public_bookable=True,
        capacity=100, cleaning_rate_daily=Decimal("45.00"),
        public_description="Our largest room.",
    )
    private = Room(
        floor_id=floor.id, room_code="I-1", name="Back Office", usage_type="office",
        occupancy_mode=OccupancyMode.INTERNAL, bookable=True, public_bookable=False,
    )
    projector = Equipment(name="Projector")
    screen = Equipment(name="Screen")
    db_session.add_all([public, private, projector, screen])
    db_session.flush()
    db_session.add_all([
        # Loose kit: the form offers a quantity for it.
        RoomEquipment(room_id=public.id, equipment_id=projector.id, quantity=2, fixed=False),
        # Installed: part of the room, no quantity field, no request line.
        RoomEquipment(room_id=public.id, equipment_id=screen.id, quantity=1, fixed=True),
    ])
    db_session.commit()
    return {
        "public": public.id, "private": private.id,
        "projector": projector.id, "screen": screen.id,
    }


def _day(offset: int = 14) -> str:
    return (datetime.now(TZ) + timedelta(days=offset)).date().isoformat()


def _form(client, rooms, **overrides) -> dict:
    page = client.get("/book/new")
    import re

    csrf = re.search(r'name="csrf_token" value="([^"]+)"', page.text).group(1)
    payload = {
        "csrf_token": csrf,
        "email": "guest@example.org",
        "first_name": "Ada",
        "last_name": "Lovelace",
        "event_title": "Community meeting",
        "start_date": _day(),
        "start_time": "10:00",
        "end_date": _day(),
        "end_time": "12:00",
        "room_id": str(rooms["public"]),
        "participants": "30",
        # Required since 10.09: the form cannot be sent without it.
        "privacy_consent": "1",
    }
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------------
# The form itself
# --------------------------------------------------------------------------


def test_public_pages_are_reachable_anonymously(client, rooms):
    for path in ("/book", "/book/new", "/book/retrieve"):
        response = client.get(path)
        assert response.status_code == 200, path


def test_public_page_does_not_render_the_admin_shell(client, rooms):
    response = client.get("/book/new")
    for marker in ('href="/parties"', 'href="/leases"', 'href="/keys"', 'href="/admin/users"'):
        assert marker not in response.text


def test_submission_requires_csrf(client, rooms):
    payload = _form(client, rooms)
    del payload["csrf_token"]
    response = client.post("/book/submit", data=payload)
    assert response.status_code == 400


def test_submission_creates_a_pending_booking(client, db_session, rooms):
    response = client.post("/book/submit", data=_form(client, rooms), follow_redirects=False)
    assert response.status_code == 303
    assert "/book/confirmation/RB-" in response.headers["location"]

    booking = db_session.scalars(select(Booking)).one()
    assert booking.status == BookingStatus.PENDING
    assert booking.source == BookingSource.PUBLIC
    assert booking.attendee_count == 30

    party = db_session.get(Party, booking.party_id)
    assert party.party_type == PartyType.EXTERNAL
    assert party.email == "guest@example.org"

    assert booking.request.requester_email == "guest@example.org"
    assert booking.request.public_ref.startswith("RB-")
    # The IP is hashed, never stored raw.
    assert booking.request.submitted_ip_hash


def test_cleaning_charge_ignores_anything_the_client_posts(client, db_session, rooms):
    """The reference app computed this in the browser and wrote what it was
    given. A forged field must not reach the stored figure."""
    payload = _form(client, rooms)
    payload["cleaning_charge"] = "0"
    payload["cleaning_rate_daily"] = "0"
    client.post("/book/submit", data=payload, follow_redirects=False)

    booking = db_session.scalars(select(Booking)).one()
    assert booking.request.cleaning_charge == Decimal("45.00")
    assert booking.request.cleaning_rate_daily == Decimal("45.00")


def test_equipment_is_recorded_and_capped(client, db_session, rooms):
    payload = _form(client, rooms)
    payload[f"equipment_{rooms['public']}_{rooms['projector']}"] = "2"
    client.post("/book/submit", data=payload, follow_redirects=False)

    booking = db_session.scalars(select(Booking)).one()
    assert len(booking.equipment_requests) == 1
    assert booking.equipment_requests[0].quantity == 2


def test_two_public_rooms_can_hold_the_same_equipment(client, db_session, rooms):
    """Every room's block is on the page, so the field names must differ.

    With a bare `equipment_<id>` the second room's zero overwrote the first
    room's number in the posted form, and a request for sixty chairs arrived
    with no chairs at all.
    """
    second = Room(
        floor_id=db_session.get(Room, rooms["public"]).floor_id,
        room_code="P-2", name="Side Hall", usage_type="event",
        occupancy_mode=OccupancyMode.BOOKABLE, bookable=False, public_bookable=True,
        capacity=40,
    )
    db_session.add(second)
    db_session.flush()
    db_session.add(
        RoomEquipment(
            room_id=second.id, equipment_id=rooms["projector"], quantity=5, fixed=False
        )
    )
    db_session.commit()

    payload = _form(client, rooms)
    payload[f"equipment_{rooms['public']}_{rooms['projector']}"] = "2"
    payload[f"equipment_{second.id}_{rooms['projector']}"] = "0"
    response = client.post("/book/submit", data=payload, follow_redirects=False)
    assert response.status_code == 303

    booking = db_session.scalars(select(Booking)).all()[-1]
    assert [(line.equipment_id, line.quantity) for line in booking.equipment_requests] == [
        (rooms["projector"], 2)
    ]


def test_a_room_card_hands_its_room_to_the_form(client, rooms):
    """Choosing a room on the landing page is a choice already made."""
    page = client.get("/book/new", params={"room": rooms["public"]}).text
    marker = f'name="room_id" value="{rooms["public"]}"'
    chosen = page[page.index(marker):page.index(marker) + 200]
    assert "checked" in chosen

    # A room the public cannot book, and plain nonsense, open the form as
    # usual rather than failing: a stale link is not an error.
    for value in (rooms["private"], "banana", ""):
        response = client.get("/book/new", params={"room": value})
        assert response.status_code == 200
        assert "checked" not in response.text.split('name="room_id"')[1][:200]


def test_a_request_without_the_privacy_consent_is_refused(client, db_session, rooms):
    """The checkbox is `required` in the browser; this is the check that
    decides, because a form post does not have to come from the browser."""
    payload = _form(client, rooms)
    del payload["privacy_consent"]

    response = client.post("/book/submit", data=payload, follow_redirects=False)
    assert response.status_code == 400
    assert db_session.scalars(select(Booking)).all() == []


def test_the_ticked_notes_are_written_into_the_request(client, db_session, rooms):
    """The tick list is an input aid, not a new column: what it produces is
    the same free-text note, with the written part last."""
    payload = _form(
        client, rooms,
        note_step_free="1", note_children="1",
        additional_info="Aufbau ab 16 Uhr.",
    )
    assert client.post("/book/submit", data=payload, follow_redirects=False).status_code == 303

    booking = db_session.scalars(select(Booking)).all()[-1]
    assert booking.request.additional_info.splitlines() == [
        "Barrierefreier Zugang nötig",
        "Kinder sind dabei",
        "Aufbau ab 16 Uhr.",
    ]


def test_installed_equipment_cannot_be_requested(client, db_session, rooms):
    """`fixed` kit comes with the room.

    The form lists it without a field, so a posted quantity is not an answer
    to any question the page asked -- and it must not become a request line.
    """
    payload = _form(client, rooms)
    payload[f"equipment_{rooms['public']}_{rooms['screen']}"] = "1"
    response = client.post("/book/submit", data=payload, follow_redirects=False)
    assert response.status_code == 303

    booking = db_session.scalars(select(Booking)).all()[-1]
    assert [line.equipment_id for line in booking.equipment_requests] == []


def test_the_form_does_not_quote_a_cleaning_price(client, rooms, db_session):
    """The rate is a back-office number: computed and stored, never quoted."""
    page = client.get("/book/new")
    assert "Reinigung" not in page.text
    assert "45 €" not in page.text

    payload = _form(client, rooms)
    assert client.post("/book/submit", data=payload, follow_redirects=False).status_code == 303
    booking = db_session.scalars(select(Booking)).all()[-1]
    assert booking.request.cleaning_charge == Decimal("45.00")


def test_equipment_over_the_room_stock_is_refused(client, db_session, rooms):
    payload = _form(client, rooms)
    payload[f"equipment_{rooms['public']}_{rooms['projector']}"] = "99"
    response = client.post("/book/submit", data=payload)
    assert response.status_code == 400
    assert db_session.scalars(select(Booking)).all() == []


def test_a_non_public_room_cannot_be_booked(client, db_session, rooms):
    payload = _form(client, rooms, room_id=str(rooms["private"]))
    response = client.post("/book/submit", data=payload)
    assert response.status_code == 400
    assert db_session.scalars(select(Booking)).all() == []


def test_missing_email_is_reported_not_swallowed(client, rooms):
    payload = _form(client, rooms, email="")
    response = client.post("/book/submit", data=payload)
    assert response.status_code == 400


def test_honeypot_submission_is_silently_discarded(client, db_session, rooms):
    """Telling a bot it was detected only helps it."""
    payload = _form(client, rooms)
    payload["website"] = "http://spam.example"
    response = client.post("/book/submit", data=payload, follow_redirects=False)
    assert response.status_code == 303
    assert db_session.scalars(select(Booking)).all() == []


def test_rate_limit_trips(client, db_session, rooms):
    last = None
    for index in range(7):
        last = client.post(
            "/book/submit",
            data=_form(
                client, rooms, event_title=f"Meeting {index}",
                start_time=f"{9 + index:02d}:00", end_time=f"{10 + index:02d}:00",
            ),
        )
    assert last.status_code == 429


# --------------------------------------------------------------------------
# The public API
# --------------------------------------------------------------------------


def test_public_rooms_expose_nothing_internal(client, rooms):
    response = client.get("/api/v1/public/rooms")
    assert response.status_code == 200
    body = response.json()
    assert [room["name"] for room in body] == ["Main Hall"]
    for leaked in ("floor_id", "occupancy_mode", "meter_number", "rentable", "room_code"):
        assert leaked not in body[0]


def test_availability_shows_intervals_only(client, db_session, rooms):
    """The reference app published every booking's event title to the world."""
    client.post("/book/submit", data=_form(client, rooms), follow_redirects=False)
    booking = db_session.scalars(select(Booking)).one()
    booking.status = BookingStatus.APPROVED
    db_session.commit()

    response = client.get(
        f"/api/v1/public/rooms/{rooms['public']}/availability",
        params={"from": _day(1), "to": _day(60)},
    )
    assert response.status_code == 200
    assert len(response.json()) == 1
    assert set(response.json()[0]) == {"start_at", "end_at"}
    assert "Community meeting" not in response.text


def test_availability_refuses_a_non_public_room(client, rooms):
    """Otherwise it is an occupancy oracle for the whole building."""
    response = client.get(
        f"/api/v1/public/rooms/{rooms['private']}/availability",
        params={"from": _day(1), "to": _day(30)},
    )
    assert response.status_code == 404


def test_quote_matches_what_gets_stored(client, db_session, rooms):
    quote = client.get(
        "/api/v1/public/quote",
        params={
            "room_id": rooms["public"],
            "start": f"{_day()}T10:00",
            "end": f"{_day()}T12:00",
        },
    )
    assert quote.status_code == 200
    quoted = Decimal(quote.json()["cleaning_charge"])

    client.post("/book/submit", data=_form(client, rooms), follow_redirects=False)
    booking = db_session.scalars(select(Booking)).one()
    assert booking.request.cleaning_charge == quoted


# --------------------------------------------------------------------------
# Managing a booking
# --------------------------------------------------------------------------


def _make_booking(client, db_session, rooms) -> BookingRequest:
    client.post("/book/submit", data=_form(client, rooms), follow_redirects=False)
    return db_session.scalars(select(BookingRequest)).one()


def test_a_valid_token_opens_the_booking(client, db_session, rooms):
    request_row = _make_booking(client, db_session, rooms)
    token = make_manage_token(
        booking_request_id=request_row.id, token_version=request_row.token_version
    )
    response = client.get("/book/manage", params={"t": token})
    assert response.status_code == 200
    assert request_row.public_ref in response.text


def test_the_reference_alone_grants_nothing(client, db_session, rooms):
    """The reference app let a six-digit number in the URL read and write a
    stranger's name, email, address and billing details."""
    request_row = _make_booking(client, db_session, rooms)
    assert client.get("/book/manage", params={"t": request_row.public_ref}).status_code == 403


def test_a_tampered_token_is_refused(client, db_session, rooms):
    request_row = _make_booking(client, db_session, rooms)
    token = make_manage_token(
        booking_request_id=request_row.id, token_version=request_row.token_version
    )
    assert client.get("/book/manage", params={"t": token[:-4] + "AAAA"}).status_code == 403
    assert client.get("/book/manage", params={"t": ""}).status_code == 403


def test_a_stale_token_version_is_refused(client, db_session, rooms):
    """Cancelling bumps token_version, so links already sent stop working."""
    request_row = _make_booking(client, db_session, rooms)
    stale = make_manage_token(booking_request_id=request_row.id, token_version=0)
    assert client.get("/book/manage", params={"t": stale}).status_code == 403


def test_a_token_for_one_booking_cannot_open_another(client, db_session, rooms):
    first = _make_booking(client, db_session, rooms)
    client.post(
        "/book/submit",
        data=_form(
            client, rooms, email="other@example.org", event_title="Other",
            start_time="15:00", end_time="17:00",
        ),
        follow_redirects=False,
    )
    rows = db_session.scalars(select(BookingRequest)).all()
    second = [row for row in rows if row.id != first.id][0]

    token = make_manage_token(booking_request_id=first.id, token_version=first.token_version)
    response = client.get("/book/manage", params={"t": token})
    assert first.public_ref in response.text
    assert second.public_ref not in response.text


def test_customer_cancellation_revokes_the_link(client, db_session, rooms):
    request_row = _make_booking(client, db_session, rooms)
    token = make_manage_token(
        booking_request_id=request_row.id, token_version=request_row.token_version
    )
    page = client.get("/book/manage", params={"t": token})
    import re

    csrf = re.search(r'name="csrf_token" value="([^"]+)"', page.text).group(1)

    response = client.post(
        "/book/manage/cancel", data={"csrf_token": csrf, "t": token}
    )
    assert response.status_code == 200

    booking = db_session.scalars(select(Booking)).one()
    db_session.refresh(booking)
    assert booking.status == BookingStatus.CANCELLED
    # Cancelled, not deleted -- the reference app hard-deleted here.
    assert db_session.get(Booking, booking.id) is not None
    # And the link is dead.
    assert client.get("/book/manage", params={"t": token}).status_code == 403


def test_retrieve_answers_identically_for_known_and_unknown_references(client, db_session, rooms):
    """The reference app returned 404 for an unknown booking number and 200 for
    a known one -- an enumeration oracle with no rate limit."""
    request_row = _make_booking(client, db_session, rooms)
    page = client.get("/book/retrieve")
    import re

    csrf = re.search(r'name="csrf_token" value="([^"]+)"', page.text).group(1)

    known = client.post(
        "/book/retrieve",
        data={"csrf_token": csrf, "public_ref": request_row.public_ref, "email": "guest@example.org"},
    )
    unknown = client.post(
        "/book/retrieve",
        data={"csrf_token": csrf, "public_ref": "RB-NOTREAL", "email": "guest@example.org"},
    )
    wrong_email = client.post(
        "/book/retrieve",
        data={"csrf_token": csrf, "public_ref": request_row.public_ref, "email": "attacker@example.org"},
    )

    assert known.status_code == unknown.status_code == wrong_email.status_code == 200
    assert known.text == unknown.text == wrong_email.text


# --------------------------------------------------------------------------
# Privacy
# --------------------------------------------------------------------------


def test_public_pages_load_nothing_from_a_third_party(client, rooms):
    """A public page must not hand every visitor's IP to a CDN before it paints.

    On an internal admin page that is a minor matter. On a public page for a
    German organisation it is the fact pattern of the LG Muenchen ruling
    (3 O 17493/20), so fonts and icons are self-hosted.
    """
    import re
    from urllib.parse import urlparse

    for path in ("/book", "/book/new", "/book/retrieve"):
        page = client.get(path)
        # Only resources the browser fetches before paint count -- a <link>
        # stylesheet or any src. Navigational <a href> (e.g. the footer's
        # legally required Impressum/Datenschutz links to the org site) does
        # not hand out an IP.
        resource_urls = re.findall(
            r'<link\b[^>]*\bhref="(https?://[^"]+)"', page.text
        ) + re.findall(r'\bsrc="(https?://[^"]+)"', page.text)
        hosts = {urlparse(url).hostname for url in resource_urls}
        third_party = {host for host in hosts if host not in {"testserver", None}}
        assert not third_party, f"{path} loads from {third_party}"


def test_self_hosted_font_and_icon_files_are_actually_present(client):
    """The CSS is useless if the files it points at were never vendored."""
    import re

    fonts = client.get("/static/vendor/fonts/fonts.css")
    assert fonts.status_code == 200
    referenced = sorted(set(re.findall(r"url\(([^)]+)\)", fonts.text)))
    assert referenced, "fonts.css references no font files"
    for ref in referenced:
        assert client.get(ref).status_code == 200, f"missing font file {ref}"

    icons = client.get("/static/vendor/fontawesome/css/all.min.css")
    assert icons.status_code == 200
    for name in sorted(set(re.findall(r"url\(\.\./webfonts/([a-z0-9.-]+)\)", icons.text))):
        assert client.get(f"/static/vendor/fontawesome/webfonts/{name}").status_code == 200


def test_status_is_shown_translated_not_as_a_raw_enum_value(client, db_session, rooms):
    """`_('pending')` looks up a msgid that was never extracted.

    The catalogue holds 'Pending', so passing the lowercase enum value straight
    to gettext leaked the raw English onto a German page.
    """
    from app.core.i18n import _load_translations

    request_row = _make_booking(client, db_session, rooms)
    token = make_manage_token(
        booking_request_id=request_row.id, token_version=request_row.token_version
    )
    page = client.get("/book/manage", params={"t": token})
    assert page.status_code == 200
    assert _load_translations("de").gettext("Pending") in page.text
    assert ">pending<" not in page.text


def test_the_charge_carries_the_indicative_caveat_where_it_is_shown(
    client, db_session, rooms
):
    """A figure a customer reads is a quote unless it says otherwise, and no
    finance surface stands behind it.

    The request form no longer shows one at all -- see
    ``test_the_form_does_not_quote_a_cleaning_price``. The booking's own page
    still does, because that is the charge they will be invoiced.
    """
    from app.core.i18n import _load_translations

    request_row = _make_booking(client, db_session, rooms)
    token = make_manage_token(
        booking_request_id=request_row.id, token_version=request_row.token_version
    )
    page = client.get("/book/manage", params={"t": token})
    caveat = _load_translations("de").gettext(
        "This figure is indicative. Invoicing is handled separately."
    )
    assert caveat in page.text


# --------------------------------------------------------------------------
# Customer edit -- the flow the old platform had at /modify_booking/<number>
# --------------------------------------------------------------------------


def _edit_page(client, request_row):
    token = make_manage_token(
        booking_request_id=request_row.id, token_version=request_row.token_version
    )
    page = client.get("/book/manage/edit", params={"t": token})
    return token, page


def _edit_payload(client, page, token, **overrides):
    import re

    csrf = re.search(r'name="csrf_token" value="([^"]+)"', page.text).group(1)
    payload = {
        "csrf_token": csrf,
        "t": token,
        "event_title": "Community meeting",
        "start_date": _day(),
        "start_time": "10:00",
        "end_date": _day(),
        "end_time": "12:00",
        "room_id": "",
        "participants": "30",
    }
    payload.update(overrides)
    return payload


def test_edit_page_needs_the_signed_token(client, db_session, rooms):
    """The old platform served this at /modify_booking/<number> with no
    authentication at all -- an enumerable six-digit number gave read and
    write access to a stranger's name, email, address and billing details."""
    request_row = _make_booking(client, db_session, rooms)
    assert client.get("/book/manage/edit", params={"t": request_row.public_ref}).status_code == 403
    assert client.get("/book/manage/edit", params={"t": ""}).status_code == 403

    _, page = _edit_page(client, request_row)
    assert page.status_code == 200
    assert "Community meeting" in page.text


def test_customer_can_change_their_booking(client, db_session, rooms):
    request_row = _make_booking(client, db_session, rooms)
    token, page = _edit_page(client, request_row)
    payload = _edit_payload(
        client, page, token,
        event_title="Nachbarschaftstreffen",
        start_time="14:00", end_time="16:00",
        room_id=str(rooms["public"]), participants="55",
    )
    response = client.post("/book/manage/edit", data=payload, follow_redirects=False)
    assert response.status_code == 303, response.text[:300]

    booking = db_session.scalars(select(Booking)).one()
    db_session.refresh(booking)
    assert booking.title == "Nachbarschaftstreffen"
    assert booking.attendee_count == 55
    assert booking.start_at.hour == 14


def test_editing_requires_csrf(client, db_session, rooms):
    request_row = _make_booking(client, db_session, rooms)
    token, page = _edit_page(client, request_row)
    payload = _edit_payload(client, page, token, room_id=str(rooms["public"]))
    del payload["csrf_token"]
    assert client.post("/book/manage/edit", data=payload).status_code == 400


def test_editing_re_checks_availability(client, db_session, rooms):
    """The single biggest hole in the old platform's anti-double-booking story:
    its modify route checked nothing, so booking a free slot and editing it
    onto a taken one bypassed the conflict check entirely."""
    first = _make_booking(client, db_session, rooms)
    booking_one = db_session.get(Booking, first.booking_id)
    booking_one.status = BookingStatus.APPROVED
    db_session.commit()

    # A second request in a slot that does not clash.
    client.post(
        "/book/submit",
        data=_form(
            client, rooms, email="other@example.org", event_title="Later",
            start_time="16:00", end_time="18:00",
        ),
        follow_redirects=False,
    )
    second = [
        row for row in db_session.scalars(select(BookingRequest)).all() if row.id != first.id
    ][0]

    token, page = _edit_page(client, second)
    payload = _edit_payload(
        client, page, token, event_title="Later",
        start_time="10:30", end_time="11:30", room_id=str(rooms["public"]),
    )
    response = client.post("/book/manage/edit", data=payload)
    assert response.status_code == 409
    assert "already taken" in response.text

    db_session.refresh(booking_one)
    moved = db_session.get(Booking, second.booking_id)
    db_session.refresh(moved)
    assert moved.start_at.hour == 16, "the booking must not have moved"


def test_editing_an_approved_booking_returns_it_to_pending(client, db_session, rooms):
    """The customer changed what staff agreed to, so the agreement lapses.
    Without this, someone could get a quiet slot approved and then move it."""
    request_row = _make_booking(client, db_session, rooms)
    booking = db_session.get(Booking, request_row.booking_id)
    booking.status = BookingStatus.APPROVED
    db_session.commit()

    token, page = _edit_page(client, request_row)
    payload = _edit_payload(
        client, page, token, event_title="Changed", room_id=str(rooms["public"])
    )
    assert client.post("/book/manage/edit", data=payload, follow_redirects=False).status_code == 303

    db_session.refresh(booking)
    assert booking.status == BookingStatus.PENDING


def test_the_email_address_cannot_be_changed_through_the_form(client, db_session, rooms):
    """It is the address the link was sent to and the key the party was
    resolved by. The old platform let the form rewrite it, which hands the
    booking to whoever types a new address."""
    request_row = _make_booking(client, db_session, rooms)
    token, page = _edit_page(client, request_row)
    assert 'name="email"' not in page.text

    payload = _edit_payload(
        client, page, token, room_id=str(rooms["public"]), email="attacker@example.org"
    )
    client.post("/book/manage/edit", data=payload, follow_redirects=False)

    db_session.refresh(request_row)
    assert request_row.requester_email == "guest@example.org"


def test_editing_recomputes_the_cleaning_charge(client, db_session, rooms):
    request_row = _make_booking(client, db_session, rooms)
    token, page = _edit_page(client, request_row)
    payload = _edit_payload(
        client, page, token, room_id=str(rooms["public"]),
        start_date=_day(), end_date=_day(20), cleaning_charge="0",
    )
    client.post("/book/manage/edit", data=payload, follow_redirects=False)

    db_session.refresh(request_row)
    assert request_row.cleaning_days and request_row.cleaning_days > 1
    assert request_row.cleaning_charge == Decimal("45.00") * request_row.cleaning_days


def test_a_cancelled_booking_cannot_be_edited_back_to_life(client, db_session, rooms):
    request_row = _make_booking(client, db_session, rooms)
    booking = db_session.get(Booking, request_row.booking_id)
    booking.status = BookingStatus.CANCELLED
    db_session.commit()

    token = make_manage_token(
        booking_request_id=request_row.id, token_version=request_row.token_version
    )
    page = client.get("/book/manage/edit", params={"t": token})
    # Falls back to the read-only view rather than offering an edit form.
    assert 'action="/book/manage/edit"' not in page.text


# --------------------------------------------------------------------------
# Liability insurance
# --------------------------------------------------------------------------


def _csrf(client, path: str) -> str:
    import re

    page = client.get(path)
    return re.search(r'name="csrf_token" value="([^"]+)"', page.text).group(1)


@pytest.fixture
def object_store(monkeypatch):
    """Stand in for MinIO, which the test environment does not run.

    Same shape as tests/test_key_inventory_api.py uses for photo uploads.
    """
    stored: dict[str, bytes] = {}

    def fake_upload_bytes(*, object_key, data, content_type=None):
        stored[object_key] = data
        return object_key

    def fake_delete_object(*, object_key):
        stored.pop(object_key, None)

    monkeypatch.setattr("app.services.booking_documents.upload_bytes", fake_upload_bytes)
    monkeypatch.setattr("app.services.booking_documents.delete_object", fake_delete_object)
    return stored


def test_the_insurance_answer_has_three_states(client, db_session, rooms):
    """Yes, no, and never asked. The third is not the same as the second.

    A booking made by staff or through the portal is never put the question,
    and recording that as "no cover" would invent a fact about the requester.
    """
    client.post("/book/submit", data=_form(client, rooms), follow_redirects=False)
    booking = db_session.scalars(select(Booking)).one()
    assert booking.request.liability_insurance is None


def test_answering_no_records_a_no(client, db_session, rooms):
    client.post(
        "/book/submit",
        data=_form(client, rooms, liability_insurance="no"),
        follow_redirects=False,
    )
    booking = db_session.scalars(select(Booking)).one()
    assert booking.request.liability_insurance is False
    assert booking.documents == []


def test_a_certificate_sent_with_the_form_is_stored(client, db_session, rooms, object_store):
    response = client.post(
        "/book/submit",
        data=_form(client, rooms, liability_insurance="yes"),
        files={"insurance_document": ("cover.pdf", b"%PDF-1.4 fake", "application/pdf")},
        follow_redirects=False,
    )
    assert response.status_code == 303

    booking = db_session.scalars(select(Booking)).one()
    db_session.refresh(booking)
    assert booking.request.liability_insurance is True
    assert len(booking.documents) == 1
    certificate = booking.documents[0]
    assert certificate.document_type == DocumentType.INSURANCE
    assert certificate.original_filename == "cover.pdf"
    # The stored key is generated, never built from the submitted name.
    assert "cover" not in certificate.object_key


def test_a_certificate_is_ignored_when_the_answer_is_no(client, db_session, rooms, object_store):
    """Otherwise "no cover" plus an attachment stores a contradiction."""
    client.post(
        "/book/submit",
        data=_form(client, rooms, liability_insurance="no"),
        files={"insurance_document": ("cover.pdf", b"%PDF-1.4 fake", "application/pdf")},
        follow_redirects=False,
    )
    booking = db_session.scalars(select(Booking)).one()
    db_session.refresh(booking)
    assert booking.documents == []


def test_an_unacceptable_attachment_is_refused_before_anything_is_created(
    client, db_session, rooms, object_store
):
    """Checked before the booking, and the form comes back with the answer.

    Dropping the file quietly and confirming the booking would leave someone
    believing they had sent proof of cover that we never received.
    """
    response = client.post(
        "/book/submit",
        data=_form(client, rooms, liability_insurance="yes"),
        files={"insurance_document": ("virus.exe", b"MZ", "application/x-msdownload")},
        follow_redirects=False,
    )
    assert response.status_code == 400
    assert "PDF" in response.text
    # What they typed is still in the form; only the file has to change.
    assert "Community meeting" in response.text
    assert db_session.scalars(select(Booking)).first() is None


def test_a_booking_survives_storage_being_down(client, db_session, rooms, monkeypatch):
    """Object storage failing must not cost us the request.

    By the time the file is written the booking is committed. A 500 here would
    lose a form the visitor has already filled in, to save a file they can
    send again through their manage link.
    """
    def explode(**kwargs):
        raise RuntimeError("bucket unreachable")

    monkeypatch.setattr("app.services.booking_documents.upload_bytes", explode)

    response = client.post(
        "/book/submit",
        data=_form(client, rooms, liability_insurance="yes"),
        files={"insurance_document": ("cover.pdf", b"%PDF-1.4 fake", "application/pdf")},
        follow_redirects=False,
    )
    assert response.status_code == 303

    booking = db_session.scalars(select(Booking)).one()
    db_session.refresh(booking)
    # Recorded as promised and outstanding -- which the admin card says, and
    # which the requester can put right themselves.
    assert booking.request.liability_insurance is True
    assert booking.documents == []


def _booking_with_promise(client, db_session, rooms):
    client.post(
        "/book/submit",
        data=_form(client, rooms, liability_insurance="yes"),
        follow_redirects=False,
    )
    booking = db_session.scalars(select(Booking)).one()
    return booking, make_manage_token(
        booking_request_id=booking.request.id, token_version=booking.request.token_version
    )


def test_the_certificate_can_be_sent_on_later(client, db_session, rooms, object_store):
    booking, token = _booking_with_promise(client, db_session, rooms)
    response = client.post(
        "/book/manage/insurance",
        data={"csrf_token": _csrf(client, f"/book/manage?t={token}"), "t": token},
        files={"insurance_document": ("late.pdf", b"%PDF-1.4 fake", "application/pdf")},
    )
    assert response.status_code == 200

    db_session.expire_all()
    booking = db_session.get(Booking, booking.id)
    assert len(booking.documents) == 1
    assert booking.documents[0].original_filename == "late.pdf"


def test_a_second_upload_replaces_the_first(client, db_session, rooms, object_store):
    """One current certificate, not a pile of near-identical PDFs."""
    booking, token = _booking_with_promise(client, db_session, rooms)
    for name in ("first.pdf", "second.pdf"):
        client.post(
            "/book/manage/insurance",
            data={"csrf_token": _csrf(client, f"/book/manage?t={token}"), "t": token},
            files={"insurance_document": (name, b"%PDF-1.4 fake", "application/pdf")},
        )

    db_session.expire_all()
    booking = db_session.get(Booking, booking.id)
    assert len(booking.documents) == 1
    assert booking.documents[0].original_filename == "second.pdf"


def test_uploading_needs_the_signed_token_not_the_reference(client, db_session, rooms, object_store):
    """The quotable reference authorises nothing, here as everywhere else."""
    booking, token = _booking_with_promise(client, db_session, rooms)
    response = client.post(
        "/book/manage/insurance",
        data={
            "csrf_token": _csrf(client, f"/book/manage?t={token}"),
            "t": booking.request.public_ref,
        },
        files={"insurance_document": ("late.pdf", b"%PDF-1.4 fake", "application/pdf")},
    )
    assert response.status_code == 403

    db_session.expire_all()
    assert db_session.get(Booking, booking.id).documents == []
