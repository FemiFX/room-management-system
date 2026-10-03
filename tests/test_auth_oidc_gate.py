from __future__ import annotations

from fastapi import status
import pytest
from sqlalchemy import select

from app.api import routes_auth
from app.models.enums import Role
from app.models.user import User
from app.services.users import OIDCLoginError, OIDCUserInfo, provision_oidc_preapproved_user


def test_preapproved_user_first_oidc_login_binds_subject(db_session):
    user = User(email="allowed@example.com", display_name="Allowed", role=Role.ADMIN, is_active=True)
    db_session.add(user)
    db_session.commit()

    logged_in = provision_oidc_preapproved_user(
        db_session,
        oidc=OIDCUserInfo(
            subject="oidc-sub-1",
            issuer="https://issuer.example.com",
            email="allowed@example.com",
            display_name="Allowed User",
        ),
    )

    assert logged_in.id == user.id
    assert logged_in.oidc_subject == "oidc-sub-1"
    assert logged_in.oidc_issuer == "https://issuer.example.com"


def test_oidc_denies_unknown_user(db_session):
    with pytest.raises(OIDCLoginError):
        provision_oidc_preapproved_user(
            db_session,
            oidc=OIDCUserInfo(
                subject="oidc-sub-unknown",
                issuer="https://issuer.example.com",
                email="unknown@example.com",
                display_name="Unknown",
            ),
        )


def test_oidc_denies_inactive_user(db_session):
    user = User(email="inactive@example.com", display_name="Inactive", role=Role.VIEWER, is_active=False)
    db_session.add(user)
    db_session.commit()

    with pytest.raises(OIDCLoginError):
        provision_oidc_preapproved_user(
            db_session,
            oidc=OIDCUserInfo(
                subject="oidc-sub-inactive",
                issuer="https://issuer.example.com",
                email="inactive@example.com",
                display_name="Inactive",
            ),
        )


def test_oidc_denies_subject_mismatch(db_session):
    user = User(
        email="bound@example.com",
        display_name="Bound",
        role=Role.ADMIN,
        is_active=True,
        oidc_subject="oidc-original",
        oidc_issuer="https://issuer.example.com",
    )
    db_session.add(user)
    db_session.commit()

    with pytest.raises(OIDCLoginError):
        provision_oidc_preapproved_user(
            db_session,
            oidc=OIDCUserInfo(
                subject="oidc-other",
                issuer="https://issuer.example.com",
                email="bound@example.com",
                display_name="Bound",
            ),
        )


def test_auth_callback_logs_in_preapproved_user(client, db_session, monkeypatch):
    user = User(email="callback@example.com", display_name="Callback", role=Role.ADMIN, is_active=True)
    db_session.add(user)
    db_session.commit()

    async def fake_fetch_userinfo(_request):
        return {
            "userinfo": {
                "sub": "oidc-callback-sub",
                "iss": "https://issuer.example.com",
                "email": "callback@example.com",
                "name": "Callback User",
            }
        }

    monkeypatch.setattr(routes_auth, "fetch_userinfo", fake_fetch_userinfo)

    response = client.get("/auth/callback", follow_redirects=False)
    assert response.status_code == status.HTTP_303_SEE_OTHER

    me = client.get("/api/v1/auth/me")
    assert me.status_code == 200
    payload = me.json()
    assert payload["email"] == "callback@example.com"

    db_user = db_session.scalar(select(User).where(User.email == "callback@example.com"))
    assert db_user is not None
    assert db_user.oidc_subject == "oidc-callback-sub"
