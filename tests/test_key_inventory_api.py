from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.models.building import Building
from app.models.enums import OccupancyMode, PartyType
from app.models.floor import Floor
from app.models.party import Party
from app.models.room import Room


def _seed_room_and_party(db_session):
    building = Building(name="Main")
    db_session.add(building)
    db_session.flush()

    floor = Floor(building_id=building.id, name="Ground", floor_number=0)
    db_session.add(floor)
    db_session.flush()

    room = Room(
        floor_id=floor.id,
        room_code="G-101",
        name="Office 101",
        usage_type="office",
        occupancy_mode=OccupancyMode.LEASABLE,
        rentable=True,
        bookable=False,
        is_active=True,
    )
    party = Party(party_type=PartyType.PERSON, name="Jane Holder", is_active=True)
    db_session.add_all([room, party])
    db_session.commit()
    return room, party


def test_key_inventory_decrements_and_increments(client, dev_login, db_session):
    csrf = dev_login(role="admin", email="keys-admin@example.com")
    room, party = _seed_room_and_party(db_session)

    key_response = client.post(
        "/api/v1/keys",
        headers={"x-csrf-token": csrf},
        json={
            "key_code": "K-G101",
            "description": "Office 101",
            "hanging_location": "Reception Board",
            "total_quantity": 2,
            "master_key": False,
            "is_active": True,
        },
    )
    assert key_response.status_code == 201
    key_payload = key_response.json()
    key_id = key_payload["id"]
    assert key_payload["total_quantity"] == 2
    assert key_payload["available_quantity"] == 2
    assert key_payload["hanging_location"] == "Reception Board"

    first_issue_at = datetime(2026, 3, 26, 9, 0, tzinfo=timezone.utc)
    first_assignment = client.post(
        "/api/v1/key-assignments",
        headers={"x-csrf-token": csrf},
        json={
            "key_id": key_id,
            "room_id": room.id,
            "party_id": party.id,
            "issued_at": first_issue_at.isoformat(),
        },
    )
    assert first_assignment.status_code == 201
    first_assignment_id = first_assignment.json()["id"]

    second_assignment = client.post(
        "/api/v1/key-assignments",
        headers={"x-csrf-token": csrf},
        json={
            "key_id": key_id,
            "room_id": room.id,
            "party_id": party.id,
            "issued_at": (first_issue_at + timedelta(hours=1)).isoformat(),
        },
    )
    assert second_assignment.status_code == 201

    keys_after_two_assignments = client.get("/api/v1/keys")
    assert keys_after_two_assignments.status_code == 200
    key_after_assign = next(k for k in keys_after_two_assignments.json() if k["id"] == key_id)
    assert key_after_assign["available_quantity"] == 0

    third_assignment = client.post(
        "/api/v1/key-assignments",
        headers={"x-csrf-token": csrf},
        json={
            "key_id": key_id,
            "room_id": room.id,
            "party_id": party.id,
            "issued_at": (first_issue_at + timedelta(hours=2)).isoformat(),
        },
    )
    assert third_assignment.status_code == 400
    assert third_assignment.json()["detail"] == "No available quantity for this key."

    returned_at = (first_issue_at + timedelta(hours=3)).isoformat()
    return_response = client.post(
        f"/api/v1/key-assignments/{first_assignment_id}/return",
        headers={"x-csrf-token": csrf},
        json={"returned_at": returned_at},
    )
    assert return_response.status_code == 200

    keys_after_return = client.get("/api/v1/keys")
    assert keys_after_return.status_code == 200
    key_after_return = next(k for k in keys_after_return.json() if k["id"] == key_id)
    assert key_after_return["available_quantity"] == 1
    assert key_after_return["hanging_location"] == "Reception Board"

    return_again = client.post(
        f"/api/v1/key-assignments/{first_assignment_id}/return",
        headers={"x-csrf-token": csrf},
        json={"returned_at": (first_issue_at + timedelta(hours=4)).isoformat()},
    )
    assert return_again.status_code == 400
    assert return_again.json()["detail"] == "Assignment is already returned."


def test_key_update_respects_assigned_quantity(client, dev_login, db_session):
    csrf = dev_login(role="admin", email="keys-editor@example.com")
    room, party = _seed_room_and_party(db_session)

    key_response = client.post(
        "/api/v1/keys",
        headers={"x-csrf-token": csrf},
        json={
            "key_code": "K-EDIT-1",
            "description": "Edit Me",
            "hanging_location": "Reception Board",
            "total_quantity": 2,
            "master_key": False,
            "is_active": True,
        },
    )
    assert key_response.status_code == 201
    key_id = key_response.json()["id"]

    issue_at = datetime(2026, 3, 26, 12, 0, tzinfo=timezone.utc)
    first_assignment = client.post(
        "/api/v1/key-assignments",
        headers={"x-csrf-token": csrf},
        json={
            "key_id": key_id,
            "room_id": room.id,
            "party_id": party.id,
            "issued_at": issue_at.isoformat(),
        },
    )
    assert first_assignment.status_code == 201

    second_assignment = client.post(
        "/api/v1/key-assignments",
        headers={"x-csrf-token": csrf},
        json={
            "key_id": key_id,
            "room_id": room.id,
            "party_id": party.id,
            "issued_at": (issue_at + timedelta(hours=1)).isoformat(),
        },
    )
    assert second_assignment.status_code == 201

    update_conflict = client.patch(
        f"/api/v1/keys/{key_id}",
        headers={"x-csrf-token": csrf},
        json={"total_quantity": 1, "hanging_location": "Security Desk"},
    )
    assert update_conflict.status_code == 400
    assert "cannot be below currently assigned quantity" in update_conflict.json()["detail"]

    update_ok = client.patch(
        f"/api/v1/keys/{key_id}",
        headers={"x-csrf-token": csrf},
        json={"total_quantity": 2, "hanging_location": "Security Desk"},
    )
    assert update_ok.status_code == 200
    payload = update_ok.json()
    assert payload["total_quantity"] == 2
    assert payload["available_quantity"] == 0
    assert payload["hanging_location"] == "Security Desk"

    return_first = client.post(
        f"/api/v1/key-assignments/{first_assignment.json()['id']}/return",
        headers={"x-csrf-token": csrf},
        json={"returned_at": (issue_at + timedelta(hours=2)).isoformat()},
    )
    assert return_first.status_code == 200

    update_downsize = client.patch(
        f"/api/v1/keys/{key_id}",
        headers={"x-csrf-token": csrf},
        json={"total_quantity": 1},
    )
    assert update_downsize.status_code == 200
    payload = update_downsize.json()
    assert payload["total_quantity"] == 1
    assert payload["available_quantity"] == 0
    assert payload["hanging_location"] == "Security Desk"

    third_assignment = client.post(
        "/api/v1/key-assignments",
        headers={"x-csrf-token": csrf},
        json={
            "key_id": key_id,
            "room_id": room.id,
            "party_id": party.id,
            "issued_at": (issue_at + timedelta(hours=3)).isoformat(),
        },
    )
    assert third_assignment.status_code == 400
    assert third_assignment.json()["detail"] == "No available quantity for this key."


def test_key_assignment_upload_receipt(client, dev_login, db_session, monkeypatch):
    csrf = dev_login(role="admin", email="keys-upload@example.com")
    room, party = _seed_room_and_party(db_session)

    uploaded = {}

    def fake_upload_bytes(*, object_key, data, content_type=None):
        uploaded["object_key"] = object_key
        uploaded["size"] = len(data)
        uploaded["content_type"] = content_type

    monkeypatch.setattr("app.api.routes_assets.upload_bytes", fake_upload_bytes)

    key_response = client.post(
        "/api/v1/keys",
        headers={"x-csrf-token": csrf},
        json={
            "key_code": "K-UPLOAD-1",
            "description": "With receipt",
            "hanging_location": "Desk",
            "total_quantity": 1,
            "master_key": False,
            "is_active": True,
        },
    )
    assert key_response.status_code == 201
    key_id = key_response.json()["id"]

    issue_at = datetime(2026, 4, 9, 8, 30, tzinfo=timezone.utc)
    assignment = client.post(
        "/api/v1/key-assignments/upload",
        headers={"x-csrf-token": csrf},
        data={
            "key_id": str(key_id),
            "room_id": str(room.id),
            "party_id": str(party.id),
            "issued_at": issue_at.isoformat(),
            "issue_note": "Signed",
        },
        files={"receipt_file": ("receipt.pdf", b"dummy signed content", "application/pdf")},
    )
    assert assignment.status_code == 201
    payload = assignment.json()
    assert payload["issue_receipt_object_key"].startswith("documents/key_receipts/")
    assert payload["issue_receipt_filename"] == "receipt.pdf"
    assert payload["issue_receipt_mime_type"] == "application/pdf"
    assert payload["issue_receipt_size"] == len(b"dummy signed content")
    assert uploaded["object_key"] == payload["issue_receipt_object_key"]
    assert uploaded["size"] == len(b"dummy signed content")


def test_key_can_be_assigned_to_room_on_create_and_update(client, dev_login, db_session):
    csrf = dev_login(role="admin", email="keys-room-link@example.com")
    room, _party = _seed_room_and_party(db_session)

    key_response = client.post(
        "/api/v1/keys",
        headers={"x-csrf-token": csrf},
        json={
            "key_code": "K-ROOM-1",
            "description": "Room-linked key",
            "hanging_location": "Reception",
            "total_quantity": 1,
            "master_key": False,
            "is_active": True,
            "room_id": room.id,
        },
    )
    assert key_response.status_code == 201
    payload = key_response.json()
    assert payload["room_id"] == room.id
    key_id = payload["id"]

    update_response = client.patch(
        f"/api/v1/keys/{key_id}",
        headers={"x-csrf-token": csrf},
        json={"room_id": None},
    )
    assert update_response.status_code == 200
    assert update_response.json()["room_id"] is None


def test_key_delete_requires_no_assignment_history(client, dev_login, db_session):
    csrf = dev_login(role="admin", email="keys-delete@example.com")
    room, party = _seed_room_and_party(db_session)

    key_response = client.post(
        "/api/v1/keys",
        headers={"x-csrf-token": csrf},
        json={
            "key_code": "K-DELETE-1",
            "description": "Delete candidate",
            "hanging_location": "Desk",
            "total_quantity": 1,
            "master_key": False,
            "is_active": True,
        },
    )
    assert key_response.status_code == 201
    key_id = key_response.json()["id"]

    assignment = client.post(
        "/api/v1/key-assignments",
        headers={"x-csrf-token": csrf},
        json={
            "key_id": key_id,
            "room_id": room.id,
            "party_id": party.id,
            "issued_at": datetime(2026, 4, 9, 10, 0, tzinfo=timezone.utc).isoformat(),
        },
    )
    assert assignment.status_code == 201

    delete_blocked = client.delete(f"/api/v1/keys/{key_id}", headers={"x-csrf-token": csrf})
    assert delete_blocked.status_code == 400
    assert "assignment history" in delete_blocked.json()["detail"].lower()

    free_key = client.post(
        "/api/v1/keys",
        headers={"x-csrf-token": csrf},
        json={
            "key_code": "K-DELETE-2",
            "description": "Unused key",
            "hanging_location": "Desk",
            "total_quantity": 1,
            "master_key": False,
            "is_active": True,
        },
    )
    assert free_key.status_code == 201
    free_key_id = free_key.json()["id"]

    delete_ok = client.delete(f"/api/v1/keys/{free_key_id}", headers={"x-csrf-token": csrf})
    assert delete_ok.status_code == 204
