"""The member portal: instant confirm, own bookings only, nothing else.

The containment sweep lives in test_member_containment.py; this covers what a
member can legitimately do once inside.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import select

from app.models.booking import Booking
from app.models.building import Building
from app.models.enums import BookingStatus, OccupancyMode, PartyType, Role
from app.models.floor import Floor
from app.models.party import Party
from app.models.room import Room
from app.models.user import User

TZ = ZoneInfo("Europe/Berlin")


def _future(days_ahead: int = 7, hour: int = 10) -> datetime:
    base = datetime.now(TZ) + timedelta(days=days_ahead)
    return base.replace(hour=hour, minute=0, second=0, microsecond=0)


@pytest.fixture
def rooms(db_session):
    building = Building(name="Main")
    db_session.add(building)
    db_session.flush()
    floor = Floor(building_id=building.id, name="G", floor_number=0)
    db_session.add(floor)
    db_session.flush()
    internal = Room(
        floor_id=floor.id, room_code="I-1", name="Team Room", usage_type="meeting",
        occupancy_mode=OccupancyMode.BOOKABLE, bookable=True, public_bookable=False,
        capacity=10, cleaning_rate_daily=Decimal("20.00"),
    )
    public_only = Room(
        floor_id=floor.id, room_code="P-1", name="Public Hall", usage_type="event",
        occupancy_mode=OccupancyMode.BOOKABLE, bookable=False, public_bookable=True,
    )
    db_session.add_all([internal, public_only])
    db_session.commit()
    return {"internal": internal.id, "public_only": public_only.id}


def _link_member(db_session, email: str, name: str = "Member") -> int:
    """Give the member session a party, as the Nextcloud sync would."""
    party = Party(party_type=PartyType.PERSON, name=name, email=email, is_active=True)
    db_session.add(party)
    db_session.flush()
    user = db_session.scalar(select(User).where(User.email == email))
    user.party_id = party.id
    db_session.commit()
    return party.id


def _payload(room_id: int, hour: int = 10, days: int = 7, **extra) -> dict:
    return {
        "room_id": room_id,
        "title": "Team sync",
        "start_at": _future(days, hour).isoformat(),
        "end_at": _future(days, hour + 1).isoformat(),
        **extra,
    }


def test_member_books_a_room_and_it_is_confirmed_immediately(client, dev_login, db_session, rooms):
    csrf = dev_login(role="member", email="m1@example.org", display_name="Member One")
    _link_member(db_session, "m1@example.org")

    response = client.post(
        "/api/v1/portal/bookings", json=_payload(rooms["internal"]), headers={"x-csrf-token": csrf}
    )
    assert response.status_code == 201, response.json()
    assert response.json()["status"] == "approved"


def test_second_member_is_told_immediately_that_the_room_is_taken(
    client, dev_login, db_session, rooms
):
    """The requirement in one test: not a queue, not a pending request -- a
    refusal, with the clashing interval so the UI can say when."""
    csrf = dev_login(role="member", email="m1@example.org", display_name="Member One")
    _link_member(db_session, "m1@example.org")
    first = client.post(
        "/api/v1/portal/bookings", json=_payload(rooms["internal"]), headers={"x-csrf-token": csrf}
    )
    assert first.status_code == 201

    client.post("/auth/logout", headers={"x-csrf-token": csrf})
    csrf2 = dev_login(role="member", email="m2@example.org", display_name="Member Two")
    _link_member(db_session, "m2@example.org", name="Member Two")

    clash = client.post(
        "/api/v1/portal/bookings", json=_payload(rooms["internal"]), headers={"x-csrf-token": csrf2}
    )
    assert clash.status_code == 409
    detail = clash.json()["detail"]
    assert detail["code"] == "room_unavailable"
    assert detail["conflicts"][0]["start_at"] is not None
    assert len(db_session.scalars(select(Booking)).all()) == 1


def test_touching_bookings_are_both_accepted(client, dev_login, db_session, rooms):
    csrf = dev_login(role="member", email="m1@example.org", display_name="Member One")
    _link_member(db_session, "m1@example.org")

    first = client.post(
        "/api/v1/portal/bookings", json=_payload(rooms["internal"], hour=10),
        headers={"x-csrf-token": csrf},
    )
    second = client.post(
        "/api/v1/portal/bookings", json=_payload(rooms["internal"], hour=11),
        headers={"x-csrf-token": csrf},
    )
    assert first.status_code == 201
    assert second.status_code == 201, second.json()


def test_member_cannot_book_a_public_only_room(client, dev_login, db_session, rooms):
    csrf = dev_login(role="member", email="m1@example.org", display_name="Member One")
    _link_member(db_session, "m1@example.org")
    response = client.post(
        "/api/v1/portal/bookings", json=_payload(rooms["public_only"]), headers={"x-csrf-token": csrf}
    )
    assert response.status_code == 404


def test_unlinked_member_gets_a_clear_message(client, dev_login, rooms):
    """Never silently create a second party for them -- that forks identity."""
    csrf = dev_login(role="member", email="nolink@example.org", display_name="No Link")
    response = client.post(
        "/api/v1/portal/bookings", json=_payload(rooms["internal"]), headers={"x-csrf-token": csrf}
    )
    assert response.status_code == 409
    assert "not linked" in response.json()["detail"].lower()


def test_booking_beyond_the_horizon_is_refused(client, dev_login, db_session, rooms):
    csrf = dev_login(role="member", email="m1@example.org", display_name="Member One")
    _link_member(db_session, "m1@example.org")
    response = client.post(
        "/api/v1/portal/bookings", json=_payload(rooms["internal"], days=400),
        headers={"x-csrf-token": csrf},
    )
    assert response.status_code == 400
    assert "days ahead" in response.json()["detail"]


def test_overlong_booking_is_refused(client, dev_login, db_session, rooms):
    """Instant confirm with no cap would let one person hold a room all week."""
    csrf = dev_login(role="member", email="m1@example.org", display_name="Member One")
    _link_member(db_session, "m1@example.org")
    payload = _payload(rooms["internal"])
    payload["end_at"] = _future(7, 10).replace(hour=23).isoformat()
    response = client.post(
        "/api/v1/portal/bookings", json=payload, headers={"x-csrf-token": csrf}
    )
    assert response.status_code == 400
    assert "hours" in response.json()["detail"]


def test_availability_exposes_intervals_only(client, dev_login, db_session, rooms):
    """A member may know a room is busy, not who booked it or why."""
    csrf = dev_login(role="member", email="m1@example.org", display_name="Member One")
    _link_member(db_session, "m1@example.org")
    client.post(
        "/api/v1/portal/bookings", json=_payload(rooms["internal"], **{"title": "Secret retreat"}),
        headers={"x-csrf-token": csrf},
    )

    response = client.get(
        "/api/v1/portal/availability",
        params={
            "room_id": rooms["internal"],
            "from": _future(1).isoformat(),
            "to": _future(30).isoformat(),
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert set(body[0]) == {"start_at", "end_at"}
    assert "Secret retreat" not in response.text


def test_member_cannot_cancel_someone_elses_booking(client, dev_login, db_session, rooms):
    csrf = dev_login(role="member", email="m1@example.org", display_name="Member One")
    _link_member(db_session, "m1@example.org")
    created = client.post(
        "/api/v1/portal/bookings", json=_payload(rooms["internal"]), headers={"x-csrf-token": csrf}
    )
    booking_id = created.json()["id"]

    client.post("/auth/logout", headers={"x-csrf-token": csrf})
    csrf2 = dev_login(role="member", email="m2@example.org", display_name="Member Two")
    _link_member(db_session, "m2@example.org", name="Member Two")

    response = client.post(
        f"/api/v1/portal/bookings/{booking_id}/cancel", headers={"x-csrf-token": csrf2}
    )
    # 404, not 403: a 403 would confirm the booking exists.
    assert response.status_code == 404


def test_cancelling_frees_the_room(client, dev_login, db_session, rooms):
    csrf = dev_login(role="member", email="m1@example.org", display_name="Member One")
    _link_member(db_session, "m1@example.org")
    created = client.post(
        "/api/v1/portal/bookings", json=_payload(rooms["internal"]), headers={"x-csrf-token": csrf}
    )
    booking_id = created.json()["id"]

    cancelled = client.post(
        f"/api/v1/portal/bookings/{booking_id}/cancel", headers={"x-csrf-token": csrf}
    )
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "cancelled"

    again = client.post(
        "/api/v1/portal/bookings", json=_payload(rooms["internal"]), headers={"x-csrf-token": csrf}
    )
    assert again.status_code == 201

    # Cancelled, not deleted.
    assert db_session.get(Booking, booking_id) is not None


def test_my_bookings_lists_only_mine(client, dev_login, db_session, rooms):
    csrf = dev_login(role="member", email="m1@example.org", display_name="Member One")
    _link_member(db_session, "m1@example.org")
    client.post(
        "/api/v1/portal/bookings", json=_payload(rooms["internal"]), headers={"x-csrf-token": csrf}
    )

    client.post("/auth/logout", headers={"x-csrf-token": csrf})
    csrf2 = dev_login(role="member", email="m2@example.org", display_name="Member Two")
    _link_member(db_session, "m2@example.org", name="Member Two")

    response = client.get("/api/v1/portal/bookings")
    assert response.status_code == 200
    assert response.json() == []


def test_portal_rooms_excludes_public_only_rooms(client, dev_login, db_session, rooms):
    dev_login(role="member", email="m1@example.org", display_name="Member One")
    response = client.get("/api/v1/portal/rooms")
    assert response.status_code == 200
    names = {room["name"] for room in response.json()}
    assert "Team Room" in names
    assert "Public Hall" not in names


# --------------------------------------------------------------------------
# The portal pages themselves
# --------------------------------------------------------------------------


@pytest.mark.parametrize("path", ["/portal", "/portal/book", "/portal/bookings"])
def test_portal_pages_render_for_a_member(client, dev_login, db_session, rooms, path):
    dev_login(role="member", email="m1@example.org", display_name="Member One")
    _link_member(db_session, "m1@example.org")
    response = client.get(path)
    assert response.status_code == 200
    # None of them may render the admin shell.
    for marker in ('href="/parties"', 'href="/leases"', 'href="/keys"', 'href="/admin/users"'):
        assert marker not in response.text, f"{path} leaks admin navigation"


def test_book_page_offers_only_internally_bookable_rooms(client, dev_login, db_session, rooms):
    dev_login(role="member", email="m1@example.org", display_name="Member One")
    _link_member(db_session, "m1@example.org")
    response = client.get("/portal/book")
    assert "Team Room" in response.text
    assert "Public Hall" not in response.text


def test_unlinked_member_is_warned_before_trying_to_book(client, dev_login, rooms):
    """The service refuses an unlinked member, so say so up front rather than
    letting them fill in a form that cannot succeed."""
    dev_login(role="member", email="nolink@example.org", display_name="No Link")
    response = client.get("/portal/book")
    assert response.status_code == 200
    # The warning is shown in the page's language (German by default here), so
    # assert the translated string rather than the English source.
    from app.core.i18n import _load_translations

    warning = _load_translations("de").gettext(
        "Your account is not linked to a contact record yet, so you cannot book. "
        "Please contact an administrator."
    )
    assert warning in response.text
    assert 'id="portal-booking-form"' not in response.text


def test_bookings_page_lists_my_bookings_only(client, dev_login, db_session, rooms):
    csrf = dev_login(role="member", email="m1@example.org", display_name="Member One")
    _link_member(db_session, "m1@example.org")
    client.post(
        "/api/v1/portal/bookings",
        json=_payload(rooms["internal"], **{"title": "Sprint planning"}),
        headers={"x-csrf-token": csrf},
    )
    assert "Sprint planning" in client.get("/portal/bookings").text

    client.post("/auth/logout", headers={"x-csrf-token": csrf})
    dev_login(role="member", email="m2@example.org", display_name="Member Two")
    _link_member(db_session, "m2@example.org", name="Member Two")
    assert "Sprint planning" not in client.get("/portal/bookings").text
