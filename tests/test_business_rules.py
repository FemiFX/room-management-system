from __future__ import annotations

from datetime import date, datetime, timedelta

import pytest

from app.models.booking import Booking
from app.models.building import Building
from app.models.enums import BookingStatus, LeaseStatus, OccupancyMode, PartyType
from app.models.internal_room_assignment import InternalRoomAssignment
from app.models.floor import Floor
from app.models.lease import Lease
from app.models.party import Party
from app.models.room import Room
from app.services.business_rules import (
    ensure_active_party,
    ensure_booking_approval_allowed,
    ensure_no_active_internal_assignment_overlap,
    ensure_no_active_lease_overlap,
    ensure_team_party_for_internal_assignment,
    validate_room_can_have_internal_assignment,
)


def _make_room_and_party(db_session):
    building = Building(name="Main Building")
    db_session.add(building)
    db_session.flush()

    floor = Floor(building_id=building.id, name="Ground", floor_number=0)
    db_session.add(floor)
    db_session.flush()

    room = Room(
        floor_id=floor.id,
        room_code="G-101",
        name="Room 101",
        usage_type="office",
        occupancy_mode=OccupancyMode.LEASABLE,
        rentable=True,
        bookable=True,
    )
    party = Party(party_type=PartyType.ORGANIZATION, name="Tenant A", is_active=True)
    db_session.add_all([room, party])
    db_session.commit()
    return room, party


def test_no_overlapping_active_leases_rule(db_session):
    room, party = _make_room_and_party(db_session)

    existing = Lease(
        room_id=room.id,
        party_id=party.id,
        start_date=date(2026, 1, 1),
        end_date=date(2026, 12, 31),
        monthly_rent=1000,
        status=LeaseStatus.ACTIVE,
        currency="EUR",
    )
    db_session.add(existing)
    db_session.commit()

    with pytest.raises(ValueError):
        ensure_no_active_lease_overlap(
            db_session,
            room_id=room.id,
            start_date=date(2026, 6, 1),
            end_date=date(2026, 9, 1),
        )


def test_no_overlapping_approved_bookings_rule(db_session):
    room, party = _make_room_and_party(db_session)

    existing = Booking(
        room_id=room.id,
        party_id=party.id,
        title="Existing",
        start_at=datetime(2026, 5, 1, 10, 0, 0),
        end_at=datetime(2026, 5, 1, 12, 0, 0),
        status=BookingStatus.APPROVED,
    )
    db_session.add(existing)
    db_session.commit()

    with pytest.raises(ValueError):
        ensure_booking_approval_allowed(
            db_session,
            room_id=room.id,
            start_at=datetime(2026, 5, 1, 11, 0, 0),
            end_at=datetime(2026, 5, 1, 13, 0, 0),
        )


def test_key_assignment_requires_active_party(db_session):
    inactive = Party(party_type=PartyType.PERSON, name="Inactive", is_active=False)
    db_session.add(inactive)
    db_session.commit()

    with pytest.raises(ValueError):
        ensure_active_party(db_session, party_id=inactive.id)


def test_internal_assignment_requires_team_and_internal_room(db_session):
    room, _party = _make_room_and_party(db_session)
    invalid_party = Party(party_type=PartyType.PERSON, name="Not Team", is_active=True)
    db_session.add(invalid_party)
    db_session.commit()

    with pytest.raises(ValueError):
        ensure_team_party_for_internal_assignment(db_session, party_id=invalid_party.id)

    with pytest.raises(ValueError):
        validate_room_can_have_internal_assignment(room)


def test_internal_assignment_no_second_active_overlap(db_session):
    building = Building(name="Main B")
    db_session.add(building)
    db_session.flush()
    floor = Floor(building_id=building.id, name="L1", floor_number=1)
    db_session.add(floor)
    db_session.flush()
    room = Room(
        floor_id=floor.id,
        room_code="INT-1",
        name="Internal One",
        usage_type="office",
        occupancy_mode=OccupancyMode.INTERNAL,
        rentable=False,
        bookable=False,
        is_active=True,
    )
    team = Party(party_type=PartyType.TEAM, name="Ops Team", is_active=True)
    db_session.add_all([room, team])
    db_session.flush()
    assignment = InternalRoomAssignment(
        room_id=room.id,
        party_id=team.id,
        start_date=date(2026, 4, 1),
        end_date=None,
    )
    db_session.add(assignment)
    db_session.commit()

    with pytest.raises(ValueError):
        ensure_no_active_internal_assignment_overlap(
            db_session,
            room_id=room.id,
            start_date=date(2026, 4, 15),
            end_date=None,
        )
