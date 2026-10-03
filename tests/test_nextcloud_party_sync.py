from __future__ import annotations

from app.core.config import get_settings
from app.models.enums import PartyType
from app.models.party import Party
from app.services.party_sync import sync_nextcloud_person_parties


class _FakeNCClient:
    def __init__(self, users: dict[str, dict]):
        self._users = users

    def list_users(self, search: str = "") -> list[str]:
        return list(self._users.keys())

    def user_info(self, user_id: str) -> dict:
        return self._users[user_id]


def _enable_sync(monkeypatch):
    monkeypatch.setenv("RMS_NEXTCLOUD_SYNC_ENABLED", "true")
    monkeypatch.setenv("RMS_NEXTCLOUD_URL", "https://cloud.example.org")
    monkeypatch.setenv("RMS_NEXTCLOUD_ADMIN_USER", "admin")
    monkeypatch.setenv("RMS_NEXTCLOUD_APP_PASSWORD", "secret")
    get_settings.cache_clear()


def test_nextcloud_sync_first_run_seeds_and_links_by_email(db_session, monkeypatch):
    _enable_sync(monkeypatch)
    existing = Party(party_type=PartyType.PERSON, name="Manual User", email="fallback@example.com", is_active=True)
    db_session.add(existing)
    db_session.commit()

    client = _FakeNCClient(
        {
            "u-active": {"displayname": "Active User", "email": "active@example.com", "enabled": "true"},
            "u-linked": {"displayname": "Linked User", "email": "fallback@example.com", "enabled": 1},
            "u-disabled": {"displayname": "Disabled User", "email": "disabled@example.com", "enabled": False},
        }
    )
    stats = sync_nextcloud_person_parties(db_session, client=client)

    assert stats["synced"] == 2
    assert stats["created"] == 1
    assert stats["deactivated"] == 0
    assert stats["disabled_or_missing"] == 1

    linked = db_session.get(Party, existing.id)
    assert linked is not None
    assert linked.nc_user_id == "u-linked"
    assert linked.name == "Linked User"
    assert linked.email == "fallback@example.com"
    assert linked.is_active is True

    created = db_session.query(Party).filter(Party.nc_user_id == "u-active").one()
    assert created.name == "Active User"
    assert created.party_type == PartyType.PERSON


def test_nextcloud_sync_subsequent_adds_updates_and_deactivates(db_session, monkeypatch):
    _enable_sync(monkeypatch)
    existing_synced = Party(
        party_type=PartyType.PERSON,
        name="Old Name",
        email="old@example.com",
        is_active=True,
        nc_user_id="u-1",
    )
    missing_synced = Party(
        party_type=PartyType.PERSON,
        name="Will Disable",
        email="missing@example.com",
        is_active=True,
        nc_user_id="u-missing",
    )
    db_session.add_all([existing_synced, missing_synced])
    db_session.commit()

    client = _FakeNCClient(
        {
            "u-1": {"displayname": "Updated Name", "email": "new@example.com", "enabled": True},
            "u-2": {"displayname": "Brand New", "email": "new-user@example.com", "enabled": "yes"},
        }
    )
    stats = sync_nextcloud_person_parties(db_session, client=client)

    assert stats["synced"] == 2
    assert stats["created"] == 1
    assert stats["updated"] == 1
    assert stats["deactivated"] == 1

    refreshed = db_session.query(Party).filter(Party.nc_user_id == "u-1").one()
    assert refreshed.name == "Updated Name"
    assert refreshed.email == "new@example.com"
    assert refreshed.is_active is True

    new_party = db_session.query(Party).filter(Party.nc_user_id == "u-2").one()
    assert new_party.name == "Brand New"
    assert new_party.is_active is True

    deactivated = db_session.query(Party).filter(Party.nc_user_id == "u-missing").one()
    assert deactivated.is_active is False

