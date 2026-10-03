from __future__ import annotations

from datetime import date

from app.models.building import Building
from app.models.enums import OccupancyMode, PartyType
from app.models.floor import Floor
from app.models.party import Party
from app.models.room import Room


def _seed_room_and_teams(db_session):
    building = Building(name="HQ")
    db_session.add(building)
    db_session.flush()

    floor = Floor(building_id=building.id, name="L1", floor_number=1)
    db_session.add(floor)
    db_session.flush()

    internal_room = Room(
        floor_id=floor.id,
        room_code="INT-201",
        name="Internal Room",
        usage_type="office",
        occupancy_mode=OccupancyMode.INTERNAL,
        rentable=False,
        bookable=False,
        is_active=True,
    )
    leasable_room = Room(
        floor_id=floor.id,
        room_code="L-202",
        name="Leasable Room",
        usage_type="office",
        occupancy_mode=OccupancyMode.LEASABLE,
        rentable=True,
        bookable=False,
        is_active=True,
    )
    team_a = Party(party_type=PartyType.TEAM, name="Team A", is_active=True)
    team_b = Party(party_type=PartyType.TEAM, name="Team B", is_active=True)
    person = Party(party_type=PartyType.PERSON, name="Jane", is_active=True)
    db_session.add_all([internal_room, leasable_room, team_a, team_b, person])
    db_session.commit()
    return internal_room, leasable_room, team_a, team_b, person


def test_internal_assignment_create_end_and_history(client, dev_login, db_session):
    csrf = dev_login(role="admin", email="internal-assignments@example.com")
    internal_room, _leasable_room, team_a, team_b, _person = _seed_room_and_teams(db_session)

    create_one = client.post(
        "/api/v1/internal-room-assignments",
        headers={"x-csrf-token": csrf},
        json={
            "room_id": internal_room.id,
            "party_id": team_a.id,
            "start_date": date(2026, 4, 10).isoformat(),
            "notes": "Initial assignment",
        },
    )
    assert create_one.status_code == 201
    payload_one = create_one.json()
    assert payload_one["room_id"] == internal_room.id
    assert payload_one["party_id"] == team_a.id
    assert payload_one["end_date"] is None

    create_second_while_active = client.post(
        "/api/v1/internal-room-assignments",
        headers={"x-csrf-token": csrf},
        json={
            "room_id": internal_room.id,
            "party_id": team_b.id,
            "start_date": date(2026, 4, 11).isoformat(),
        },
    )
    assert create_second_while_active.status_code == 400

    end_one = client.post(
        f"/api/v1/internal-room-assignments/{payload_one['id']}/end",
        headers={"x-csrf-token": csrf},
        json={"end_date": date(2026, 4, 20).isoformat(), "notes": "Moved"},
    )
    assert end_one.status_code == 200
    assert end_one.json()["end_date"] == date(2026, 4, 20).isoformat()

    create_two = client.post(
        "/api/v1/internal-room-assignments",
        headers={"x-csrf-token": csrf},
        json={
            "room_id": internal_room.id,
            "party_id": team_b.id,
            "start_date": date(2026, 4, 21).isoformat(),
            "notes": "Switched team",
        },
    )
    assert create_two.status_code == 201

    history = client.get(f"/api/v1/rooms/{internal_room.id}/internal-assignments")
    assert history.status_code == 200
    rows = history.json()
    assert len(rows) == 2
    assert rows[0]["party_id"] == team_b.id
    assert rows[1]["party_id"] == team_a.id


def test_internal_assignment_validation_errors(client, dev_login, db_session):
    csrf = dev_login(role="admin", email="internal-assignments-errors@example.com")
    internal_room, leasable_room, team_a, _team_b, person = _seed_room_and_teams(db_session)

    non_team = client.post(
        "/api/v1/internal-room-assignments",
        headers={"x-csrf-token": csrf},
        json={
            "room_id": internal_room.id,
            "party_id": person.id,
            "start_date": date(2026, 4, 10).isoformat(),
        },
    )
    assert non_team.status_code == 400

    wrong_room_type = client.post(
        "/api/v1/internal-room-assignments",
        headers={"x-csrf-token": csrf},
        json={
            "room_id": leasable_room.id,
            "party_id": team_a.id,
            "start_date": date(2026, 4, 10).isoformat(),
        },
    )
    assert wrong_room_type.status_code == 400


def test_room_detail_shows_internal_assignment(client, dev_login, db_session):
    csrf = dev_login(role="admin", email="internal-assignments-ui@example.com")
    internal_room, _leasable_room, team_a, _team_b, _person = _seed_room_and_teams(db_session)

    create_one = client.post(
        "/api/v1/internal-room-assignments",
        headers={"x-csrf-token": csrf},
        json={
            "room_id": internal_room.id,
            "party_id": team_a.id,
            "start_date": date(2026, 4, 1).isoformat(),
            "notes": "Team using room",
        },
    )
    assert create_one.status_code == 201

    detail = client.get(f"/rooms/{internal_room.id}")
    assert detail.status_code == 200
    assert "Internal Assignment" in detail.text
    assert "Team A" in detail.text
    assert "Internally Assigned" in detail.text
