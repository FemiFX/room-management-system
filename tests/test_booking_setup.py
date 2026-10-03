"""Equipment and services management -- what the old platform's admin dashboard
did and RMS could not.

RMS could add equipment through the API but never edit or remove it, so a typo
or a piece of kit that left the building was permanent. Services had no admin
surface at all; the reference app hardcoded them in two places in its source.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.models.booking_service import BookingService
from app.models.building import Building
from app.models.enums import OccupancyMode
from app.models.equipment import Equipment, RoomEquipment
from app.models.floor import Floor
from app.models.room import Room


@pytest.fixture
def room(db_session):
    building = Building(name="Haus")
    db_session.add(building)
    db_session.flush()
    floor = Floor(building_id=building.id, name="EG", floor_number=0)
    db_session.add(floor)
    db_session.flush()
    room = Room(
        floor_id=floor.id, room_code="R-1", name="Grosser Saal", usage_type="event",
        occupancy_mode=OccupancyMode.BOOKABLE, bookable=True, public_bookable=True,
    )
    db_session.add(room)
    db_session.commit()
    return room


def test_setup_page_renders(client, dev_login, room):
    dev_login(role="admin", email="a@example.org", display_name="Admin")
    response = client.get("/bookings/setup")
    assert response.status_code == 200
    assert "Grosser Saal" in response.text


def test_setup_path_is_not_read_as_a_booking_id(client, dev_login, room):
    dev_login(role="admin", email="a@example.org", display_name="Admin")
    assert client.get("/bookings/setup", follow_redirects=False).status_code == 200


def test_member_cannot_reach_booking_setup(client, dev_login, room):
    dev_login(role="member", email="m@example.org", display_name="Member")
    response = client.get("/bookings/setup", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/portal"


def test_setup_lists_the_whole_catalogue_with_absent_types_at_zero(
    client, dev_login, db_session, room
):
    """A list of only what is present cannot answer "what is missing here".

    The row is there either way; what differs is that it has no link yet, so
    the count is 0 and the plus is what turns it on.
    """
    present = Equipment(name="Beamer")
    absent = Equipment(name="Rednerpult")
    db_session.add_all([present, absent])
    db_session.flush()
    db_session.add(RoomEquipment(room_id=room.id, equipment_id=present.id, quantity=2))
    db_session.commit()

    dev_login(role="admin", email="a@example.org", display_name="Admin")
    body = client.get("/bookings/setup").text

    assert f'data-equipment="{present.id}"' in body
    assert f'data-equipment="{absent.id}"' in body
    # The absent one carries no link, which is what the plus button reads.
    absent_row = body[body.index(f'data-equipment="{absent.id}"'):]
    assert absent_row[: absent_row.index(">")].endswith('data-link=""')


# --------------------------------------------------------------------------
# The catalogue page
# --------------------------------------------------------------------------


def test_catalogue_page_renders(client, dev_login, db_session):
    db_session.add(Equipment(name="Hybrid-Kamera", category="Technik"))
    db_session.commit()
    dev_login(role="admin", email="a@example.org", display_name="Admin")

    response = client.get("/bookings/catalogue")
    assert response.status_code == 200
    assert "Hybrid-Kamera" in response.text
    assert "Technik" in response.text


def test_catalogue_path_is_not_read_as_a_booking_id(client, dev_login, room):
    """Registered above /bookings/{booking_id}, or "catalogue" is an id."""
    dev_login(role="admin", email="a@example.org", display_name="Admin")
    assert client.get("/bookings/catalogue", follow_redirects=False).status_code == 200


def test_member_cannot_reach_the_catalogue(client, dev_login, room):
    dev_login(role="member", email="m@example.org", display_name="Member")
    response = client.get("/bookings/catalogue", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/portal"


def test_catalogue_counts_where_equipment_is_used(client, dev_login, db_session, room):
    """Usage is what says whether a row can safely be deleted, so it is on
    the page rather than something to find out by trying."""
    used = Equipment(name="Stuhl")
    unused = Equipment(name="Stehtisch")
    db_session.add_all([used, unused])
    db_session.flush()
    db_session.add(RoomEquipment(room_id=room.id, equipment_id=used.id, quantity=40))
    db_session.commit()

    dev_login(role="admin", email="a@example.org", display_name="Admin")
    body = client.get("/bookings/catalogue").text

    used_row = body[body.index(f'data-equipment="{used.id}"'):][:400]
    assert 'data-rooms="1"' in used_row
    assert 'data-stock="40"' in used_row
    unused_row = body[body.index(f'data-equipment="{unused.id}"'):][:400]
    assert 'data-rooms="0"' in unused_row
    assert 'data-stock="0"' in unused_row


# --------------------------------------------------------------------------
# Equipment
# --------------------------------------------------------------------------


def test_equipment_can_be_renamed(client, dev_login, db_session):
    """There was no PATCH at all, so a typo was permanent."""
    csrf = dev_login(role="admin", email="a@example.org", display_name="Admin")
    created = client.post(
        "/api/v1/equipment", json={"name": "Bemaer"}, headers={"x-csrf-token": csrf}
    )
    assert created.status_code == 201
    equipment_id = created.json()["id"]

    fixed = client.patch(
        f"/api/v1/equipment/{equipment_id}",
        json={"name": "Beamer", "category": "AV"},
        headers={"x-csrf-token": csrf},
    )
    assert fixed.status_code == 200
    assert fixed.json()["name"] == "Beamer"
    assert fixed.json()["category"] == "AV"


def test_unused_equipment_can_be_deleted(client, dev_login, db_session):
    csrf = dev_login(role="admin", email="a@example.org", display_name="Admin")
    created = client.post(
        "/api/v1/equipment", json={"name": "Alte Leinwand"}, headers={"x-csrf-token": csrf}
    )
    equipment_id = created.json()["id"]
    assert client.delete(
        f"/api/v1/equipment/{equipment_id}", headers={"x-csrf-token": csrf}
    ).status_code == 204
    assert db_session.get(Equipment, equipment_id) is None


def test_equipment_on_a_booking_cannot_be_deleted(client, dev_login, db_session, room):
    """A booking that asked for this equipment records what was agreed;
    deleting the row would rewrite history."""
    from datetime import datetime, timedelta
    from zoneinfo import ZoneInfo

    from app.models.enums import BookingSource, BookingStatus, PartyType
    from app.models.party import Party
    from app.services.bookings import (
        BookingInput, EquipmentLine, TimeframeInput, create_booking,
    )

    equipment = Equipment(name="Beamer")
    party = Party(party_type=PartyType.EXTERNAL, name="Ada", email="ada@example.org")
    db_session.add_all([equipment, party])
    db_session.flush()
    db_session.add(RoomEquipment(room_id=room.id, equipment_id=equipment.id, quantity=2))
    db_session.commit()

    start = datetime.now(ZoneInfo("Europe/Berlin")) + timedelta(days=5)
    create_booking(
        db_session, room=room, party=party,
        data=BookingInput(
            room_id=room.id, title="Event",
            timeframe=TimeframeInput(start_at=start, end_at=start + timedelta(hours=2)),
            equipment=[EquipmentLine(equipment.id, 1)],
        ),
        source=BookingSource.PUBLIC, status=BookingStatus.PENDING,
    )

    csrf = dev_login(role="admin", email="a@example.org", display_name="Admin")
    response = client.delete(f"/api/v1/equipment/{equipment.id}", headers={"x-csrf-token": csrf})
    assert response.status_code == 400
    assert "cannot be deleted" in response.json()["detail"]


def test_room_equipment_quantity_can_be_changed_and_unlinked(client, dev_login, db_session, room):
    csrf = dev_login(role="admin", email="a@example.org", display_name="Admin")
    equipment = Equipment(name="Mikrofon")
    db_session.add(equipment)
    db_session.commit()

    link = client.post(
        "/api/v1/room-equipment",
        json={"room_id": room.id, "equipment_id": equipment.id, "quantity": 2},
        headers={"x-csrf-token": csrf},
    )
    assert link.status_code == 201
    link_id = link.json()["id"]

    changed = client.patch(
        f"/api/v1/room-equipment/{link_id}", json={"quantity": 5},
        headers={"x-csrf-token": csrf},
    )
    assert changed.status_code == 200
    assert changed.json()["quantity"] == 5

    assert client.delete(
        f"/api/v1/room-equipment/{link_id}", headers={"x-csrf-token": csrf}
    ).status_code == 204
    assert db_session.get(RoomEquipment, link_id) is None


# --------------------------------------------------------------------------
# Services
# --------------------------------------------------------------------------


def test_services_can_be_managed(client, dev_login, db_session):
    """The reference app hardcoded ["Technician", "Usher"] in its source, so
    changing the list meant a deploy."""
    csrf = dev_login(role="admin", email="a@example.org", display_name="Admin")
    created = client.post(
        "/api/v1/booking-services",
        json={"code": "Garderobe", "name": "Garderobe", "sort_order": 30},
        headers={"x-csrf-token": csrf},
    )
    assert created.status_code == 201
    # The code is normalised to a stable lowercase key.
    assert created.json()["code"] == "garderobe"

    service_id = created.json()["id"]
    renamed = client.patch(
        f"/api/v1/booking-services/{service_id}",
        json={"name": "Garderobendienst"},
        headers={"x-csrf-token": csrf},
    )
    assert renamed.json()["name"] == "Garderobendienst"
    assert renamed.json()["code"] == "garderobe", "the code must be stable"


def test_duplicate_service_code_is_rejected(client, dev_login):
    csrf = dev_login(role="admin", email="a@example.org", display_name="Admin")
    payload = {"code": "technician", "name": "Another technician"}
    assert client.post(
        "/api/v1/booking-services", json=payload, headers={"x-csrf-token": csrf}
    ).status_code in (201, 400)
    second = client.post(
        "/api/v1/booking-services", json=payload, headers={"x-csrf-token": csrf}
    )
    assert second.status_code == 400


def test_a_service_created_without_a_code_gets_one_from_its_name(client, dev_login):
    """The room panel's add field has nowhere to type a machine key.

    `code` is the identifier that survives display-name edits, so it still has
    to exist; the server derives it rather than making the caller invent one.
    """
    csrf = dev_login(role="admin", email="a@example.org", display_name="Admin")
    created = client.post(
        "/api/v1/booking-services",
        json={"name": "Garderobe & Aufsicht"},
        headers={"x-csrf-token": csrf},
    )
    assert created.status_code == 201
    assert created.json()["code"] == "garderobe-aufsicht"


def test_two_services_with_the_same_name_get_distinct_codes(client, dev_login):
    """Deriving must not collide: the second one is suffixed, not rejected."""
    csrf = dev_login(role="admin", email="a@example.org", display_name="Admin")
    payload = {"name": "Aufsicht"}
    first = client.post("/api/v1/booking-services", json=payload, headers={"x-csrf-token": csrf})
    second = client.post("/api/v1/booking-services", json=payload, headers={"x-csrf-token": csrf})
    assert first.status_code == second.status_code == 201
    assert first.json()["code"] == "aufsicht"
    assert second.json()["code"] == "aufsicht-2"


def test_deactivating_a_service_takes_it_off_the_public_form(client, dev_login, db_session):
    csrf = dev_login(role="admin", email="a@example.org", display_name="Admin")
    service = BookingService(code="usher-temp", name="Ordner")
    db_session.add(service)
    db_session.commit()

    assert "Ordner" in client.get("/api/v1/public/services").text
    client.patch(
        f"/api/v1/booking-services/{service.id}", json={"is_active": False},
        headers={"x-csrf-token": csrf},
    )
    assert "Ordner" not in client.get("/api/v1/public/services").text


def test_a_service_on_a_booking_cannot_be_deleted(client, dev_login, db_session, room):
    from datetime import datetime, timedelta
    from zoneinfo import ZoneInfo

    from app.models.enums import BookingSource, BookingStatus, PartyType
    from app.models.party import Party
    from app.services.bookings import BookingInput, ServiceLine, TimeframeInput, create_booking

    service = BookingService(code="tontechnik", name="Tontechnik")
    party = Party(party_type=PartyType.EXTERNAL, name="Ada", email="ada@example.org")
    db_session.add_all([service, party])
    db_session.commit()

    start = datetime.now(ZoneInfo("Europe/Berlin")) + timedelta(days=5)
    create_booking(
        db_session, room=room, party=party,
        data=BookingInput(
            room_id=room.id, title="Event",
            timeframe=TimeframeInput(start_at=start, end_at=start + timedelta(hours=2)),
            services=[ServiceLine(service.id)],
        ),
        source=BookingSource.PUBLIC, status=BookingStatus.PENDING,
    )

    csrf = dev_login(role="admin", email="a@example.org", display_name="Admin")
    response = client.delete(
        f"/api/v1/booking-services/{service.id}", headers={"x-csrf-token": csrf}
    )
    assert response.status_code == 400
    assert "Deactivate it instead" in response.json()["detail"]


def test_viewer_cannot_write(client, dev_login):
    csrf = dev_login(role="viewer", email="v@example.org", display_name="Viewer")
    assert client.post(
        "/api/v1/booking-services", json={"code": "x", "name": "X"},
        headers={"x-csrf-token": csrf},
    ).status_code == 403
    assert client.post(
        "/api/v1/equipment", json={"name": "X"}, headers={"x-csrf-token": csrf}
    ).status_code == 403


def test_equipment_in_a_room_cannot_be_deleted_until_it_is_unlinked(
    client, dev_login, db_session, room
):
    """Deleting cascades the room links, so it would empty every room the
    type stands in without saying so. Refuse, and name the way back."""
    csrf = dev_login(role="admin", email="a@example.org", display_name="Admin")
    equipment = Equipment(name="Leinwand")
    db_session.add(equipment)
    db_session.flush()
    link = RoomEquipment(room_id=room.id, equipment_id=equipment.id, quantity=1)
    db_session.add(link)
    db_session.commit()
    equipment_id, link_id = equipment.id, link.id

    refused = client.delete(f"/api/v1/equipment/{equipment_id}", headers={"x-csrf-token": csrf})
    assert refused.status_code == 400
    assert "1 room" in refused.json()["detail"]
    assert db_session.get(Equipment, equipment_id) is not None

    assert client.delete(
        f"/api/v1/room-equipment/{link_id}", headers={"x-csrf-token": csrf}
    ).status_code == 204
    assert client.delete(
        f"/api/v1/equipment/{equipment_id}", headers={"x-csrf-token": csrf}
    ).status_code == 204
