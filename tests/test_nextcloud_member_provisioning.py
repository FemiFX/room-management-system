"""Every active Nextcloud account should get a working RMS login.

Nextcloud is the identity provider, so the address the sync writes is the one
the OIDC gate matches on -- a synced account can sign in with no further step.
This module covers the ways that can go wrong.
"""

from __future__ import annotations

from sqlalchemy import select

from app.core.config import get_settings
from app.models.audit_log import AuditLog
from app.models.enums import PartyType, Role
from app.models.party import Party
from app.models.user import User
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


def _user(db, email: str) -> User | None:
    return db.scalar(select(User).where(User.email == email))


def test_active_account_gets_a_party_and_a_member_login(db_session, monkeypatch):
    _enable_sync(monkeypatch)
    client = _FakeNCClient(
        {"u-1": {"displayname": "Ada Lovelace", "email": "ada@example.org", "enabled": True}}
    )
    stats = sync_nextcloud_person_parties(db_session, client=client)

    assert stats["users_created"] == 1
    user = _user(db_session, "ada@example.org")
    assert user is not None
    assert user.role == Role.MEMBER
    assert user.nc_user_id == "u-1"
    assert user.party_id is not None
    assert db_session.get(Party, user.party_id).party_type == PartyType.PERSON


def test_sync_is_idempotent(db_session, monkeypatch):
    _enable_sync(monkeypatch)
    client = _FakeNCClient(
        {"u-1": {"displayname": "Ada", "email": "ada@example.org", "enabled": True}}
    )
    sync_nextcloud_person_parties(db_session, client=client)
    second = sync_nextcloud_person_parties(db_session, client=client)

    assert second["users_created"] == 0
    assert second["users_updated"] == 1
    assert len(db_session.scalars(select(User)).all()) == 1


def test_upstream_email_change_updates_the_login(db_session, monkeypatch):
    _enable_sync(monkeypatch)
    sync_nextcloud_person_parties(
        db_session,
        client=_FakeNCClient({"u-1": {"displayname": "Ada", "email": "old@example.org", "enabled": True}}),
    )
    sync_nextcloud_person_parties(
        db_session,
        client=_FakeNCClient({"u-1": {"displayname": "Ada", "email": "new@example.org", "enabled": True}}),
    )

    assert _user(db_session, "old@example.org") is None
    assert _user(db_session, "new@example.org") is not None


def test_email_collision_is_audited_not_stolen(db_session, monkeypatch):
    """An address must never move between accounts silently."""
    _enable_sync(monkeypatch)
    incumbent = User(email="taken@example.org", display_name="Incumbent", role=Role.ADMIN)
    db_session.add(incumbent)
    db_session.commit()

    sync_nextcloud_person_parties(
        db_session,
        client=_FakeNCClient({"u-1": {"displayname": "Ada", "email": "ada@example.org", "enabled": True}}),
    )
    stats = sync_nextcloud_person_parties(
        db_session,
        client=_FakeNCClient({"u-1": {"displayname": "Ada", "email": "taken@example.org", "enabled": True}}),
    )

    assert stats["email_conflicts"] == 1
    db_session.refresh(incumbent)
    assert incumbent.email == "taken@example.org"
    assert incumbent.role == Role.ADMIN
    assert _user(db_session, "ada@example.org") is not None

    conflict = db_session.scalar(
        select(AuditLog).where(AuditLog.action == "nc_user_email_conflict")
    )
    assert conflict is not None


def test_staff_role_is_never_changed_by_the_sync(db_session, monkeypatch):
    """A staff member who is also a Nextcloud user keeps their role."""
    _enable_sync(monkeypatch)
    staff = User(email="boss@example.org", display_name="Boss", role=Role.SUPER_ADMIN)
    db_session.add(staff)
    db_session.commit()

    sync_nextcloud_person_parties(
        db_session,
        client=_FakeNCClient({"u-1": {"displayname": "Boss", "email": "boss@example.org", "enabled": True}}),
    )
    db_session.refresh(staff)
    assert staff.role == Role.SUPER_ADMIN
    assert staff.party_id is not None


def test_disabling_upstream_deactivates_the_member(db_session, monkeypatch):
    _enable_sync(monkeypatch)
    sync_nextcloud_person_parties(
        db_session,
        client=_FakeNCClient(
            {f"u-{n}": {"displayname": f"U{n}", "email": f"u{n}@example.org", "enabled": True}
             for n in range(12)}
        ),
    )
    member = _user(db_session, "u0@example.org")
    assert member.role == Role.MEMBER

    remaining = {
        f"u-{n}": {"displayname": f"U{n}", "email": f"u{n}@example.org", "enabled": True}
        for n in range(1, 12)
    }
    stats = sync_nextcloud_person_parties(db_session, client=_FakeNCClient(remaining))

    assert stats["deactivated"] == 1
    assert stats["users_deactivated"] == 1
    db_session.refresh(member)
    assert member.is_active is False


def test_sweep_never_deactivates_a_staff_login(db_session, monkeypatch):
    """An integration must not be able to lock an administrator out.

    users.party_id is unique, so the staff account here is the one linked to
    the party -- exactly what happens when an admin's address matches a
    Nextcloud account.
    """
    _enable_sync(monkeypatch)
    staff = User(email="u0@example.org", display_name="Admin", role=Role.ADMIN)
    db_session.add(staff)
    db_session.commit()

    sync_nextcloud_person_parties(
        db_session,
        client=_FakeNCClient(
            {f"u-{n}": {"displayname": f"U{n}", "email": f"u{n}@example.org", "enabled": True}
             for n in range(12)}
        ),
    )
    db_session.refresh(staff)
    assert staff.party_id is not None
    assert staff.role == Role.ADMIN

    remaining = {
        f"u-{n}": {"displayname": f"U{n}", "email": f"u{n}@example.org", "enabled": True}
        for n in range(1, 12)
    }
    stats = sync_nextcloud_person_parties(db_session, client=_FakeNCClient(remaining))

    assert stats["deactivated"] == 1, "the party should still be deactivated"
    assert stats["users_deactivated"] == 0, "but never the staff login"
    db_session.refresh(staff)
    assert staff.is_active is True
    assert staff.role == Role.ADMIN


def test_account_without_an_email_is_counted_not_hidden(db_session, monkeypatch):
    """OIDC matches on email, so such an account cannot be given a login."""
    _enable_sync(monkeypatch)
    stats = sync_nextcloud_person_parties(
        db_session,
        client=_FakeNCClient({"u-1": {"displayname": "No Mail", "email": "", "enabled": True}}),
    )
    assert stats["skipped_no_email"] == 1
    assert stats["users_created"] == 0


def test_empty_upstream_response_does_not_deactivate_anyone(db_session, monkeypatch):
    """list_users pages until an empty batch, so a truncated response is
    indistinguishable from 'no more users' -- it does not raise. Sweeping on
    that would lock every member out at once."""
    _enable_sync(monkeypatch)
    sync_nextcloud_person_parties(
        db_session,
        client=_FakeNCClient(
            {f"u-{n}": {"displayname": f"U{n}", "email": f"u{n}@example.org", "enabled": True} for n in range(3)}
        ),
    )

    stats = sync_nextcloud_person_parties(db_session, client=_FakeNCClient({}))

    assert stats["deactivated"] == 0
    assert stats["users_deactivated"] == 0
    for party in db_session.scalars(select(Party).where(Party.nc_user_id.is_not(None))).all():
        assert party.is_active is True

    aborted = db_session.scalar(
        select(AuditLog).where(AuditLog.action == "nc_sync_aborted_suspicious_shrink")
    )
    assert aborted is not None


def test_large_shrink_is_refused(db_session, monkeypatch):
    """Above the ratio-guard floor, losing most accounts at once is a red flag."""
    _enable_sync(monkeypatch)
    full = {
        f"u-{n}": {"displayname": f"U{n}", "email": f"u{n}@example.org", "enabled": True}
        for n in range(12)
    }
    sync_nextcloud_person_parties(db_session, client=_FakeNCClient(full))

    remaining = {k: full[k] for k in list(full)[:4]}  # 8 of 12 would vanish
    stats = sync_nextcloud_person_parties(db_session, client=_FakeNCClient(remaining))
    assert stats["deactivated"] == 0
