from __future__ import annotations

from authentication_kit.core.config import get_settings
from authentication_kit.models.enums import Role
from authentication_kit.services.users import provision_dev_user, provision_oidc_user


def test_first_oidc_login_provisions_user(db_session, monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "oidc_admin_emails", ["admin@example.com"])

    user = provision_oidc_user(
        db_session,
        oidc_subject="oidc-subject-1",
        display_name="Admin User",
        email="admin@example.com",
        oidc_issuer="https://issuer.example.com",
    )

    assert user.id is not None
    assert user.role == Role.SUPER_ADMIN
    assert user.display_name == "Admin User"


def test_repeat_oidc_login_updates_existing_user(db_session, monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "oidc_admin_emails", [])

    first = provision_oidc_user(
        db_session,
        oidc_subject="oidc-subject-2",
        display_name="Initial Name",
        email="user@example.com",
        oidc_issuer="https://issuer.example.com",
    )

    second = provision_oidc_user(
        db_session,
        oidc_subject="oidc-subject-2",
        display_name="Updated Name",
        email="user@example.com",
        oidc_issuer="https://issuer.example.com",
    )

    assert first.id == second.id
    assert second.display_name == "Updated Name"


def test_dev_login_provisions_local_user_with_selected_role(db_session):
    user = provision_dev_user(
        db_session,
        email="local@example.com",
        display_name="Local Admin",
        role=Role.ADMIN,
    )

    assert user.oidc_subject == "dev:local@example.com"
    assert user.role == Role.ADMIN
    assert user.oidc_issuer == "dev-local"
