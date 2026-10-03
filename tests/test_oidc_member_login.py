"""The OIDC gate must survive an email change and still refuse strangers."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.models.audit_log import AuditLog
from app.models.enums import Role
from app.models.user import User
from app.services.users import OIDCLoginError, OIDCUserInfo, provision_oidc_preapproved_user


def _login(db, **kwargs) -> User:
    return provision_oidc_preapproved_user(db, oidc=OIDCUserInfo(**kwargs))


def test_subject_match_survives_an_email_change(db_session):
    """Nextcloud is the IdP, so the email path is the normal one -- but an
    address changed upstream must not lock a working account out."""
    user = User(email="old@example.org", display_name="Ada", role=Role.MEMBER, oidc_subject="sub-1")
    db_session.add(user)
    db_session.commit()

    resolved = _login(
        db_session, subject="sub-1", issuer=None, email="new@example.org", display_name="Ada"
    )
    assert resolved.id == user.id
    assert resolved.email == "new@example.org"

    updated = db_session.scalar(select(AuditLog).where(AuditLog.action == "oidc_email_updated"))
    assert updated is not None


def test_email_change_colliding_with_another_account_is_refused(db_session):
    """An address must never move between accounts."""
    incumbent = User(email="taken@example.org", display_name="Other", role=Role.ADMIN)
    user = User(email="mine@example.org", display_name="Ada", role=Role.MEMBER, oidc_subject="sub-1")
    db_session.add_all([incumbent, user])
    db_session.commit()

    resolved = _login(
        db_session, subject="sub-1", issuer=None, email="taken@example.org", display_name="Ada"
    )
    assert resolved.id == user.id
    assert resolved.email == "mine@example.org"
    db_session.refresh(incumbent)
    assert incumbent.email == "taken@example.org"

    conflict = db_session.scalar(select(AuditLog).where(AuditLog.action == "oidc_email_conflict"))
    assert conflict is not None


def test_nextcloud_uid_is_a_fallback_lookup(db_session):
    user = User(
        email="ada@example.org", display_name="Ada", role=Role.MEMBER, nc_user_id="u-1"
    )
    db_session.add(user)
    db_session.commit()

    resolved = _login(
        db_session, subject="sub-new", issuer=None, email="changed@example.org",
        display_name="Ada", preferred_username="u-1",
    )
    assert resolved.id == user.id
    assert resolved.oidc_subject == "sub-new"


def test_still_refuses_to_auto_create(db_session):
    """The pre-approval rule is unchanged: an unknown address gets nothing."""
    with pytest.raises(OIDCLoginError) as exc:
        _login(
            db_session, subject="sub-x", issuer=None, email="stranger@example.org",
            display_name="Stranger",
        )
    assert exc.value.code == "not_preapproved"


def test_member_login_works_end_to_end_after_sync(db_session):
    """What the sync writes is what the gate matches on."""
    user = User(email="ada@example.org", display_name="Ada", role=Role.MEMBER, nc_user_id="u-1")
    db_session.add(user)
    db_session.commit()

    resolved = _login(
        db_session, subject="sub-1", issuer="https://cloud.example.org",
        email="ada@example.org", display_name="Ada Lovelace",
    )
    assert resolved.role == Role.MEMBER
    assert resolved.oidc_subject == "sub-1"
    assert resolved.display_name == "Ada Lovelace"


def test_callback_passes_the_nextcloud_uid_through(client, db_session, monkeypatch):
    """The uid fallback is inert unless the callback actually forwards the claim.

    Nextcloud is the IdP, so preferred_username carries the same uid the party
    sync stores. Without this wiring an upstream email change would still lock
    a working account out.
    """
    import app.api.routes_auth as routes_auth

    user = User(
        email="stale@example.org", display_name="Ada", role=Role.MEMBER, nc_user_id="u-1"
    )
    db_session.add(user)
    db_session.commit()

    async def fake_userinfo(request):
        return {
            "userinfo": {
                "sub": "sub-1",
                "iss": "https://cloud.example.org",
                # The address upstream has changed and no longer matches.
                "email": "renamed@example.org",
                "name": "Ada Lovelace",
                "preferred_username": "u-1",
            }
        }

    monkeypatch.setattr(routes_auth, "fetch_userinfo", fake_userinfo)
    response = client.get("/auth/callback", follow_redirects=False)
    assert response.status_code == 303

    db_session.expire_all()
    resolved = db_session.get(User, user.id)
    assert resolved.oidc_subject == "sub-1"
    assert resolved.email == "renamed@example.org"
