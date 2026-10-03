from __future__ import annotations

from datetime import datetime, timezone

from app.models.building import Building
from app.models.enums import OccupancyMode, PartyType
from app.models.floor import Floor
from app.models.key import Key, KeyAssignment
from app.models.party import Party
from app.models.room import Room
from app.services.dashboard import action_center_items


def _seed_room(db_session) -> Room:
    building = Building(name="Main")
    db_session.add(building)
    db_session.flush()
    floor = Floor(building_id=building.id, name="Ground", floor_number=0)
    db_session.add(floor)
    db_session.flush()
    room = Room(
        floor_id=floor.id,
        room_code="G-100",
        name="Office",
        usage_type="office",
        occupancy_mode=OccupancyMode.LEASABLE,
        rentable=True,
        bookable=False,
        is_active=True,
    )
    db_session.add(room)
    db_session.flush()
    return room


def test_action_center_includes_recovery_and_excludes_info_item(db_session):
    room = _seed_room(db_session)
    key = Key(
        key_code="K-REC-1",
        total_quantity=1,
        available_quantity=0,
        is_active=True,
        master_key=False,
    )
    holder = Party(
        party_type=PartyType.PERSON,
        name="Synced Disabled",
        email="synced@example.com",
        is_active=False,
        nc_user_id="nc-user-1",
    )
    db_session.add_all([key, holder])
    db_session.flush()

    assignment = KeyAssignment(
        key_id=key.id,
        room_id=room.id,
        party_id=holder.id,
        issued_at=datetime.now(timezone.utc),
        issue_note="issued",
    )
    db_session.add(assignment)
    db_session.commit()

    items = action_center_items(db_session)
    codes = {item["code"] for item in items}
    assert "keys_recovery" in codes
    assert "rooms_available" not in codes

    assignment.returned_at = datetime.now(timezone.utc)
    db_session.commit()
    items_after_return = action_center_items(db_session)
    codes_after_return = {item["code"] for item in items_after_return}
    assert "keys_recovery" not in codes_after_return


def test_dashboard_and_action_center_views_are_split(client, dev_login):
    dev_login(role="admin", email="split-view@example.com")
    dashboard = client.get("/dashboard")
    assert dashboard.status_code == 200
    assert "Quick Links" in dashboard.text or "Schnellzugriffe" in dashboard.text
    assert "Open Actions" not in dashboard.text

    action_center = client.get("/action-center")
    assert action_center.status_code == 200
    assert "Open Actions" in action_center.text
