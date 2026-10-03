from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.i18n import get_default_language, normalize_language
from app.models.enums import Role
from app.models.user import User
from app.services.audit import create_audit_entry


class OIDCLoginError(Exception):
    def __init__(self, message: str, *, code: str):
        self.message = message
        self.code = code
        super().__init__(message)


@dataclass
class OIDCUserInfo:
    subject: str
    issuer: str | None
    email: str | None
    display_name: str
    #: The Nextcloud uid, when the provider sends one. A second lookup key, so
    #: an address changed upstream does not lock a working account out.
    preferred_username: str | None = None


def normalize_email(email: str | None) -> str | None:
    if email is None:
        return None
    return email.strip().lower()


def create_user(
    db: Session,
    *,
    email: str,
    display_name: str,
    role: Role,
    preferred_language: str,
    is_active: bool,
    actor_user_id: int | None,
) -> User:
    normalized = normalize_email(email)
    if not normalized:
        raise ValueError("Email is required.")

    existing = db.scalar(select(User).where(User.email == normalized))
    if existing is not None:
        raise ValueError("User with this email already exists.")

    language = normalize_language(preferred_language)
    if not language:
        raise ValueError("Preferred language is not supported.")

    user = User(
        email=normalized,
        display_name=display_name,
        role=role,
        preferred_language=language,
        is_active=is_active,
    )
    db.add(user)
    db.flush()
    create_audit_entry(
        db,
        entity_type="user",
        entity_id=user.id,
        action="created",
        actor_user_id=actor_user_id,
        before_json=None,
        after_json={
            "email": user.email,
            "role": user.role.value,
            "preferred_language": user.preferred_language,
            "is_active": user.is_active,
        },
    )
    db.commit()
    db.refresh(user)
    return user


def update_user(
    db: Session,
    *,
    user: User,
    display_name: str | None,
    role: Role | None,
    preferred_language: str | None,
    is_active: bool | None,
    actor_user_id: int,
) -> User:
    before = {
        "display_name": user.display_name,
        "role": user.role.value,
        "preferred_language": user.preferred_language,
        "is_active": user.is_active,
    }
    if display_name is not None:
        user.display_name = display_name
    if role is not None:
        user.role = role
    if preferred_language is not None:
        language = normalize_language(preferred_language)
        if not language:
            raise ValueError("Preferred language is not supported.")
        user.preferred_language = language
    if is_active is not None:
        user.is_active = is_active

    create_audit_entry(
        db,
        entity_type="user",
        entity_id=user.id,
        action="updated",
        actor_user_id=actor_user_id,
        before_json=before,
        after_json={
            "display_name": user.display_name,
            "role": user.role.value,
            "preferred_language": user.preferred_language,
            "is_active": user.is_active,
        },
    )
    db.commit()
    db.refresh(user)
    return user


def activate_user(db: Session, *, user: User, actor_user_id: int, is_active: bool) -> User:
    before = {"is_active": user.is_active}
    user.is_active = is_active
    create_audit_entry(
        db,
        entity_type="user",
        entity_id=user.id,
        action="activated" if is_active else "deactivated",
        actor_user_id=actor_user_id,
        before_json=before,
        after_json={"is_active": user.is_active},
    )
    db.commit()
    db.refresh(user)
    return user


def provision_oidc_preapproved_user(db: Session, *, oidc: OIDCUserInfo) -> User:
    email = normalize_email(oidc.email)
    if not oidc.subject:
        raise OIDCLoginError("OIDC response missing subject.", code="oidc_missing_subject")
    if not email:
        create_audit_entry(
            db,
            entity_type="auth",
            entity_id=None,
            action="oidc_denied_missing_email",
            actor_user_id=None,
            before_json=None,
            after_json={"subject": oidc.subject, "issuer": oidc.issuer},
        )
        db.commit()
        raise OIDCLoginError("OIDC response missing email.", code="oidc_missing_email")

    # Subject first, then the Nextcloud uid, then email. Nextcloud is the
    # identity provider, so the email path is the normal one -- but an address
    # changed upstream would otherwise silently lock a working account out,
    # because the row still holds the bound subject while the lookup misses.
    user = db.scalar(select(User).where(User.oidc_subject == oidc.subject))
    if user is None and oidc.preferred_username:
        user = db.scalar(select(User).where(User.nc_user_id == oidc.preferred_username))
    if user is None:
        user = db.scalar(select(User).where(User.email == email))

    if user is None:
        create_audit_entry(
            db,
            entity_type="auth",
            entity_id=None,
            action="oidc_denied_not_preapproved",
            actor_user_id=None,
            before_json=None,
            after_json={"email": email, "subject": oidc.subject, "issuer": oidc.issuer},
        )
        db.commit()
        raise OIDCLoginError("User is not pre-approved for OIDC login.", code="not_preapproved")

    if not user.is_active:
        create_audit_entry(
            db,
            entity_type="auth",
            entity_id=user.id,
            action="oidc_denied_inactive",
            actor_user_id=user.id,
            before_json=None,
            after_json={"email": email, "subject": oidc.subject},
        )
        db.commit()
        raise OIDCLoginError("User is inactive.", code="inactive")

    if user.email != email:
        # The address changed upstream. Take it if it is free; if another
        # account already holds it, keep ours and surface the clash rather
        # than moving an address between accounts.
        holder = db.scalar(select(User).where(User.email == email))
        if holder is not None and holder.id != user.id:
            create_audit_entry(
                db, entity_type="user", entity_id=user.id, action="oidc_email_conflict",
                actor_user_id=user.id, before_json={"email": user.email},
                after_json={"claimed_email": email, "held_by_user_id": holder.id},
            )
        else:
            create_audit_entry(
                db, entity_type="user", entity_id=user.id, action="oidc_email_updated",
                actor_user_id=user.id, before_json={"email": user.email},
                after_json={"email": email},
            )
            user.email = email

    if user.oidc_subject is None:
        user.oidc_subject = oidc.subject
        user.oidc_issuer = oidc.issuer
        create_audit_entry(
            db,
            entity_type="user",
            entity_id=user.id,
            action="oidc_bound",
            actor_user_id=user.id,
            before_json=None,
            after_json={"oidc_subject": oidc.subject, "oidc_issuer": oidc.issuer},
        )
    else:
        if user.oidc_subject != oidc.subject:
            create_audit_entry(
                db,
                entity_type="auth",
                entity_id=user.id,
                action="oidc_denied_subject_mismatch",
                actor_user_id=user.id,
                before_json={"expected_subject": user.oidc_subject},
                after_json={"actual_subject": oidc.subject},
            )
            db.commit()
            raise OIDCLoginError("OIDC subject mismatch.", code="subject_mismatch")
        if user.oidc_issuer and oidc.issuer and user.oidc_issuer != oidc.issuer:
            create_audit_entry(
                db,
                entity_type="auth",
                entity_id=user.id,
                action="oidc_denied_issuer_mismatch",
                actor_user_id=user.id,
                before_json={"expected_issuer": user.oidc_issuer},
                after_json={"actual_issuer": oidc.issuer},
            )
            db.commit()
            raise OIDCLoginError("OIDC issuer mismatch.", code="issuer_mismatch")

    user.display_name = oidc.display_name
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
    email = normalize_email(email)
    subject_key = email or display_name
    oidc_subject = f"dev:{subject_key.strip().lower()}"
    user = db.scalar(select(User).where(User.oidc_subject == oidc_subject))
    if user is None:
        if email:
            existing_email = db.scalar(select(User).where(User.email == email))
            if existing_email and existing_email.oidc_subject is None:
                user = existing_email
                user.oidc_subject = oidc_subject
            elif existing_email:
                user = existing_email
            else:
                user = User(email=email, display_name=display_name, role=role, is_active=True, oidc_subject=oidc_subject)
                db.add(user)
        else:
            user = User(
                email=f"{oidc_subject}@local.dev",
                display_name=display_name,
                role=role,
                preferred_language=get_default_language(),
                is_active=True,
                oidc_subject=oidc_subject,
            )
            db.add(user)
        if not user.preferred_language:
            user.preferred_language = get_default_language()
        user.oidc_issuer = "dev-local"
        user.last_login_at = datetime.now(timezone.utc)
        db.flush()
        create_audit_entry(
            db,
            entity_type="user",
            entity_id=user.id,
            action="dev_provisioned",
            actor_user_id=user.id,
            before_json=None,
            after_json={"email": user.email, "role": user.role.value},
        )
    else:
        user.display_name = display_name
        if email:
            user.email = email
        user.role = role
        user.oidc_issuer = "dev-local"
        user.last_login_at = datetime.now(timezone.utc)

    db.commit()
    db.refresh(user)
    return user
