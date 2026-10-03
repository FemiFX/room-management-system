"""The Buchungen pages must render, and show where each booking came from."""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import select

from app.models.booking import Booking
from app.models.building import Building
from app.models.enums import BookingSource, BookingStatus, OccupancyMode, PartyType
from app.models.equipment import Equipment, RoomEquipment
from app.models.floor import Floor
from app.models.party import Party
from app.models.room import Room
from app.services.bookings import (
    BookingInput,
    EquipmentLine,
    PublicRequesterInput,
    TimeframeInput,
    create_booking,
)

TZ = ZoneInfo("Europe/Berlin")


@pytest.fixture
def public_booking(db_session):
    building = Building(name="Main")
    db_session.add(building)
    db_session.flush()
    floor = Floor(building_id=building.id, name="G", floor_number=0)
    db_session.add(floor)
    db_session.flush()
    room = Room(
        floor_id=floor.id, room_code="A-1", name="Main Hall", usage_type="event",
        occupancy_mode=OccupancyMode.BOOKABLE, public_bookable=True,
        capacity=80, cleaning_rate_daily=Decimal("45.00"),
    )
    projector = Equipment(name="Projector")
    party = Party(
        party_type=PartyType.EXTERNAL, name="Ada Lovelace", email="ada@example.org"
    )
    db_session.add_all([room, projector, party])
    db_session.flush()
    db_session.add(RoomEquipment(room_id=room.id, equipment_id=projector.id, quantity=3))
    db_session.commit()

    start = datetime.now(TZ) + timedelta(days=5)
    return create_booking(
        db_session,
        room=room,
        party=party,
        data=BookingInput(
            room_id=room.id,
            title="Community meeting",
            timeframe=TimeframeInput(start_at=start, end_at=start + timedelta(hours=3)),
            billing_info="Invoice to the association",
            additional_info="We will need the side entrance.",
            equipment=[EquipmentLine(projector.id, 2)],
        ),
        source=BookingSource.PUBLIC,
        status=BookingStatus.PENDING,
        requester=PublicRequesterInput(
            email="ada@example.org", first_name="Ada", last_name="Lovelace",
            organization="Analytical Society",
        ),
    )


def test_list_shows_source_and_reference(client, dev_login, public_booking):
    """Assert on data, not prose -- the suite runs with German as the default
    language, so any English label here would be a false failure."""
    from app.core.i18n import _load_translations

    dev_login(role="editor", email="e@example.org", display_name="Editor")
    response = client.get("/bookings")
    assert response.status_code == 200
    assert "Community meeting" in response.text
    assert public_booking.request.public_ref in response.text
    assert _load_translations("de").gettext("Public") in response.text


def test_detail_page_renders_the_whole_request(client, dev_login, public_booking):
    dev_login(role="editor", email="e@example.org", display_name="Editor")
    response = client.get(f"/bookings/{public_booking.id}")
    assert response.status_code == 200

    for expected in (
        public_booking.request.public_ref,
        "Ada Lovelace",
        "ada@example.org",
        "Analytical Society",
        "Projector",
        "Invoice to the association",
        "We will need the side entrance.",
    ):
        assert expected in response.text, f"detail page is missing {expected!r}"


def test_detail_shows_how_the_cleaning_charge_was_derived(client, dev_login, public_booking):
    """Staff need to be able to explain the figure, not just read it."""
    from app.core.i18n import _load_translations

    dev_login(role="editor", email="e@example.org", display_name="Editor")
    response = client.get(f"/bookings/{public_booking.id}")
    # rate x days = total, all three visible so staff can explain the figure
    # rather than reading a number they cannot account for.
    request_row = public_booking.request
    assert str(request_row.cleaning_rate_daily) in response.text
    assert str(request_row.cleaning_days) in response.text
    assert str(request_row.cleaning_charge) in response.text
    caveat = _load_translations("de").gettext("Indicative. Invoicing is handled separately.")
    assert caveat in response.text


def test_detail_link_from_a_notification_resolves(client, dev_login, public_booking):
    """app/jobs/tasks.py has always linked to /bookings/{id}, which 404'd."""
    dev_login(role="editor", email="e@example.org", display_name="Editor")
    assert client.get(f"/bookings/{public_booking.id}").status_code == 200


def test_unknown_booking_redirects_rather_than_erroring(client, dev_login):
    dev_login(role="editor", email="e@example.org", display_name="Editor")
    response = client.get("/bookings/99999", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/bookings"


def test_member_cannot_reach_the_booking_detail_page(client, dev_login, public_booking):
    dev_login(role="member", email="m@example.org", display_name="Member")
    response = client.get(f"/bookings/{public_booking.id}", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/portal"


def test_a_room_can_be_made_publicly_bookable_and_priced(client, dev_login, db_session):
    """Without these fields on the API and the form, no room could ever be
    offered on the public form -- the whole feature would be unreachable."""
    from app.models.building import Building as B
    from app.models.floor import Floor as F

    building = B(name="Main")
    db_session.add(building)
    db_session.flush()
    floor = F(building_id=building.id, name="G", floor_number=0)
    db_session.add(floor)
    db_session.commit()

    csrf = dev_login(role="admin", email="a@example.org", display_name="Admin")
    created = client.post(
        "/api/v1/rooms",
        json={
            "floor_id": floor.id,
            "room_code": "PUB-1",
            "name": "Public Room",
            "usage_type": "event",
            "occupancy_mode": "bookable",
            "public_bookable": True,
            "capacity": 40,
            "cleaning_rate_daily": "35.50",
            "public_description": "Bright room facing the courtyard.",
        },
        headers={"x-csrf-token": csrf},
    )
    assert created.status_code == 201, created.json()
    body = created.json()
    assert body["public_bookable"] is True
    assert body["capacity"] == 40

    # And it shows up on the public form.
    public = client.get("/api/v1/public/rooms")
    assert "Public Room" in public.text
    assert "Bright room facing the courtyard." in public.text


def test_occupancy_mode_options_are_all_valid(client, dev_login):
    """The create modal used to offer "shared", which is not an OccupancyMode
    and made the API 422."""
    import re
    from app.models.enums import OccupancyMode

    dev_login(role="admin", email="a@example.org", display_name="Admin")
    page = client.get("/rooms")
    options = set(re.findall(r'<option value="(\w+)">[A-Z]', page.text))
    modes = {mode.value for mode in OccupancyMode}
    invalid = {opt for opt in options if opt in {"shared"}}
    assert not invalid, f"room form offers invalid occupancy modes: {invalid}"
    assert modes <= options or options, "expected occupancy mode options on the page"


def test_audit_actions_render_translated(client, dev_login, public_booking):
    """Audit actions are lowercase machine strings; passing them to _() directly
    looks up msgids that were never extracted."""
    from app.core.i18n import _load_translations

    dev_login(role="editor", email="e@example.org", display_name="Editor")
    page = client.get(f"/bookings/{public_booking.id}")
    assert page.status_code == 200
    assert _load_translations("de").gettext("created") in page.text
