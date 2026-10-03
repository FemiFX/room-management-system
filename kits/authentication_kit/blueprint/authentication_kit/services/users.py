from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from authentication_kit.core.config import get_settings
from authentication_kit.models.user import User
from authentication_kit.models.enums import Role
from authentication_kit.services.audit import create_audit_entry


def provision_oidc_user(
    db: Session,
    *,
    oidc_subject: str,
    display_name: str,
    email: str | None,
    oidc_issuer: str | None,
) -> User:
    user = db.scalar(select(User).where(User.oidc_subject == oidc_subject))
    settings = get_settings()
    admin_emails = set(settings.oidc_admin_emails)
    if user is None:
        role = Role.SUPER_ADMIN if email in admin_emails else Role.VIEWER
        user = User(
            oidc_subject=oidc_subject,
            display_name=display_name,
            email=email,
            oidc_issuer=oidc_issuer,
            role=role,
            last_login_at=datetime.now(timezone.utc),
        )
        db.add(user)
        db.flush()
        create_audit_entry(
            db,
            entity_type="user",
            entity_id=user.id,
            action="provisioned",
            actor_user_id=user.id,
            before_json=None,
            after_json={"email": email, "role": user.role},
        )
    else:
        user.display_name = display_name
        user.email = email
        user.oidc_issuer = oidc_issuer
        user.last_login_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(user)
    return user


def provision_dev_user(
    db: Session,
    *,
    email: str | None,
    display_name: str,
    role: Role,
) -> User:
    subject_key = email or display_name
    oidc_subject = f"dev:{subject_key.strip().lower()}"
    user = db.scalar(select(User).where(User.oidc_subject == oidc_subject))
    if user is None:
        user = User(
            oidc_subject=oidc_subject,
            display_name=display_name,
            email=email,
            oidc_issuer="dev-local",
            role=role,
            last_login_at=datetime.now(timezone.utc),
        )
        db.add(user)
        db.flush()
        create_audit_entry(
            db,
            entity_type="user",
            entity_id=user.id,
            action="dev_provisioned",
            actor_user_id=user.id,
            before_json=None,
            after_json={"email": email, "role": role},
        )
    else:
        user.display_name = display_name
        user.email = email
        user.oidc_issuer = "dev-local"
        user.role = role
        user.last_login_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(user)
    return user


def update_user_role(db: Session, *, actor: User, target: User, role: Role) -> User:
    before = {"role": target.role}
    target.role = role
    create_audit_entry(
        db,
        entity_type="user",
        entity_id=target.id,
        action="role_changed",
        actor_user_id=actor.id,
        before_json=before,
        after_json={"role": target.role},
    )
    db.commit()
    db.refresh(target)
    return target


def update_user_active(db: Session, *, actor: User, target: User, is_active: bool) -> User:
    before = {"is_active": target.is_active}
    target.is_active = is_active
    create_audit_entry(
        db,
        entity_type="user",
        entity_id=target.id,
        action="active_changed",
        actor_user_id=actor.id,
        before_json=before,
        after_json={"is_active": target.is_active},
    )
    db.commit()
    db.refresh(target)
    return target
