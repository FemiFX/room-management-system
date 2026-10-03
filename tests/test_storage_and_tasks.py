from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.jobs.tasks import scan_unreturned_keys
from app.models.building import Building
from app.models.enums import OccupancyMode, PartyType, Role
from app.models.floor import Floor
from app.models.key import Key, KeyAssignment
from app.models.notification import Notification
from app.models.party import Party
from app.models.room import Room
from app.models.user import User


def test_unreturned_key_scan_creates_notifications(db_session):
    admin = User(email="ops@example.com", display_name="Ops", role=Role.ADMIN, is_active=True)
    db_session.add(admin)
    db_session.flush()

    building = Building(name="Building")
    db_session.add(building)
    db_session.flush()

    floor = Floor(building_id=building.id, name="GF", floor_number=0)
    db_session.add(floor)
    db_session.flush()

    room = Room(
        floor_id=floor.id,
        room_code="GF-1",
        name="Room",
        usage_type="office",
        occupancy_mode=OccupancyMode.LEASABLE,
        rentable=True,
        bookable=False,
    )
    party = Party(party_type=PartyType.PERSON, name="Holder", is_active=True)
    key = Key(key_code="K-1", is_active=True)
    db_session.add_all([room, party, key])
    db_session.flush()

    assignment = KeyAssignment(
        key_id=key.id,
        room_id=room.id,
        party_id=party.id,
        issued_at=datetime.now(timezone.utc) - timedelta(days=45),
        returned_at=None,
    )
    db_session.add(assignment)
    db_session.commit()

    result = scan_unreturned_keys()
    assert result["open_assignments"] >= 1

    notifications = db_session.scalars(select(Notification).where(Notification.user_id == admin.id)).all()
    assert len(notifications) >= 1
