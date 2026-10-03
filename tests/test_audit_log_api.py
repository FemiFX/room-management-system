from __future__ import annotations

from datetime import date, datetime, timezone

from sqlalchemy import select

from app.models.audit_log import AuditLog
from app.models.building import Building
from app.models.enums import OccupancyMode
from app.models.floor import Floor
from app.models.room import Room
from app.models.user import User
from app.services.audit import audit


def _seed_room(db_session) -> Room:
    building = Building(name="HQ")
    db_session.add(building)
    db_session.flush()
    floor = Floor(building_id=building.id, name="L1", floor_number=1)
    db_session.add(floor)
    db_session.flush()
    room = Room(
        floor_id=floor.id,
        room_code="A-100",
        name="Test Room",
        usage_type="office",
        occupancy_mode=OccupancyMode.LEASABLE,
        rentable=True,
        bookable=False,
        is_active=True,
    )
    db_session.add(room)
    db_session.commit()
    return room


# ─── helper ───────────────────────────────────────────────────────────────────


def test_audit_helper_creates_entry(db_session):
    room = _seed_room(db_session)
    audit(db_session, entity=room, action="updated", actor_user_id=None, before={"name": "x"}, after={"name": "y"})
    db_session.commit()
    entries = list(db_session.scalars(select(AuditLog)).all())
    assert len(entries) == 1
    assert entries[0].entity_type == "room"
    assert entries[0].entity_id == room.id
    assert entries[0].action == "updated"
    assert entries[0].before_json == {"name": "x"}
    assert entries[0].after_json == {"name": "y"}


def test_audit_helper_with_string_entity(db_session):
    audit(db_session, entity="integration", entity_id=None, action="synced", actor_user_id=None, after={"key": "nextcloud"})
    db_session.commit()
    entries = list(db_session.scalars(select(AuditLog)).all())
    assert len(entries) == 1
    assert entries[0].entity_type == "integration"
    assert entries[0].entity_id is None


# ─── route coverage ───────────────────────────────────────────────────────────


def _seed_floor(client, csrf) -> int:
    b = client.post("/api/v1/buildings", headers={"x-csrf-token": csrf}, json={"name": "HQ"})
    assert b.status_code == 201
    f = client.post(
        "/api/v1/floors",
        headers={"x-csrf-token": csrf},
        json={"building_id": b.json()["id"], "name": "L1", "floor_number": 1},
    )
    assert f.status_code == 201
    return f.json()["id"]


def test_create_room_writes_audit(client, dev_login, db_session):
    csrf = dev_login(role="admin", email="creator@example.com")
    floor_id = _seed_floor(client, csrf)
    res = client.post(
        "/api/v1/rooms",
        headers={"x-csrf-token": csrf},
        json={
            "floor_id": floor_id,
            "room_code": "R-1",
            "name": "Room One",
            "usage_type": "office",
            "occupancy_mode": "leasable",
            "rentable": True,
            "bookable": False,
            "is_active": True,
        },
    )
    assert res.status_code == 201
    room_id = res.json()["id"]

    actor = db_session.scalar(select(User).where(User.email == "creator@example.com"))
    rows = list(
        db_session.scalars(
            select(AuditLog).where(AuditLog.entity_type == "room", AuditLog.action == "created")
        ).all()
    )
    assert len(rows) == 1
    assert rows[0].entity_id == room_id
    assert rows[0].actor_user_id == actor.id
    assert rows[0].after_json["room_code"] == "R-1"


def test_update_room_writes_before_and_after(client, dev_login, db_session):
    csrf = dev_login(role="admin", email="updater@example.com")
    floor_id = _seed_floor(client, csrf)
    create = client.post(
        "/api/v1/rooms",
        headers={"x-csrf-token": csrf},
        json={
            "floor_id": floor_id,
            "room_code": "R-2",
            "name": "Room Two",
            "usage_type": "office",
            "occupancy_mode": "leasable",
            "rentable": True,
            "bookable": False,
            "is_active": True,
        },
    )
    room_id = create.json()["id"]

    res = client.patch(
        f"/api/v1/rooms/{room_id}",
        headers={"x-csrf-token": csrf},
        json={"name": "Renamed Room"},
    )
    assert res.status_code == 200

    update_row = db_session.scalar(
        select(AuditLog).where(
            AuditLog.entity_type == "room",
            AuditLog.entity_id == room_id,
            AuditLog.action == "updated",
        )
    )
    assert update_row is not None
    assert update_row.before_json["name"] == "Room Two"
    assert update_row.after_json["name"] == "Renamed Room"


def test_delete_building_writes_audit(client, dev_login, db_session):
    csrf = dev_login(role="admin", email="deleter@example.com")
    create = client.post("/api/v1/buildings", headers={"x-csrf-token": csrf}, json={"name": "ToDelete"})
    building_id = create.json()["id"]

    res = client.delete(f"/api/v1/buildings/{building_id}", headers={"x-csrf-token": csrf})
    assert res.status_code == 204

    row = db_session.scalar(
        select(AuditLog).where(
            AuditLog.entity_type == "building",
            AuditLog.entity_id == building_id,
            AuditLog.action == "deleted",
        )
    )
    assert row is not None
    assert row.before_json["name"] == "ToDelete"


# ─── admin API ────────────────────────────────────────────────────────────────


def test_audit_list_requires_admin(client, dev_login):
    csrf = dev_login(role="editor", email="editor@example.com")
    res = client.get("/api/v1/admin/audit-logs", headers={"x-csrf-token": csrf})
    assert res.status_code == 403


def test_audit_list_filters_and_paginates(client, dev_login, db_session):
    csrf = dev_login(role="admin", email="admin-list@example.com")
    floor_id = _seed_floor(client, csrf)
    for i in range(5):
        r = client.post(
            "/api/v1/rooms",
            headers={"x-csrf-token": csrf},
            json={
                "floor_id": floor_id,
                "room_code": f"P-{i}",
                "name": f"Room {i}",
                "usage_type": "office",
                "occupancy_mode": "leasable",
                "rentable": True,
                "bookable": False,
                "is_active": True,
            },
        )
        assert r.status_code == 201

    full = client.get("/api/v1/admin/audit-logs", headers={"x-csrf-token": csrf})
    assert full.status_code == 200
    full_data = full.json()
    assert full_data["total"] >= 5
    assert all("entity_type" in item for item in full_data["items"])

    only_room = client.get(
        "/api/v1/admin/audit-logs?entity_type=room&action=created",
        headers={"x-csrf-token": csrf},
    )
    only_room_data = only_room.json()
    assert only_room_data["total"] == 5

    paged = client.get(
        "/api/v1/admin/audit-logs?entity_type=room&action=created&page_size=2&page=1",
        headers={"x-csrf-token": csrf},
    )
    paged_data = paged.json()
    assert paged_data["total"] == 5
    assert len(paged_data["items"]) == 2
    assert paged_data["page"] == 1


def test_audit_csv_export(client, dev_login, db_session):
    csrf = dev_login(role="admin", email="csv@example.com")
    client.post("/api/v1/buildings", headers={"x-csrf-token": csrf}, json={"name": "CsvBuilding"})

    res = client.get(
        "/api/v1/admin/audit-logs.csv?entity_type=building",
        headers={"x-csrf-token": csrf},
    )
    assert res.status_code == 200
    assert res.headers["content-type"].startswith("text/csv")
    body = res.text
    assert "timestamp,actor_email,actor_display_name,entity_type" in body.splitlines()[0]
    assert "building" in body
    assert "csv@example.com" in body


def test_audit_facets(client, dev_login):
    csrf = dev_login(role="admin", email="facets@example.com")
    client.post("/api/v1/buildings", headers={"x-csrf-token": csrf}, json={"name": "FacetBuilding"})

    res = client.get("/api/v1/admin/audit-logs/facets", headers={"x-csrf-token": csrf})
    assert res.status_code == 200
    data = res.json()
    assert "building" in data["entity_types"]
    assert "created" in data["actions"]
    actor_emails = [a["email"] for a in data["actors"]]
    assert "facets@example.com" in actor_emails


# ─── nextcloud password redaction ─────────────────────────────────────────────


def test_nextcloud_settings_audit_redacts_password(client, dev_login, db_session):
    csrf = dev_login(role="admin", email="nc@example.com")
    res = client.patch(
        "/api/v1/admin/integrations/nextcloud",
        headers={"x-csrf-token": csrf},
        json={
            "enabled": False,
            "url": "https://nc.example.com",
            "admin_user": "admin",
            "app_password": "super-secret-password",
            "ocs_version": "v2",
            "timeout_s": 30,
            "page_size": 100,
        },
    )
    assert res.status_code == 200

    row = db_session.scalar(
        select(AuditLog).where(AuditLog.entity_type == "integration", AuditLog.action == "updated")
    )
    assert row is not None
    assert row.after_json["app_password"] == "***"
    assert "super-secret-password" not in str(row.after_json)
    assert "super-secret-password" not in str(row.before_json or {})
