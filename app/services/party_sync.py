from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.i18n import get_default_language
from app.integrations.nextcloud_ocs import NextcloudConfig, NextcloudOCSClient
from app.models.enums import PartyType, Role
from app.models.party import Party
from app.models.user import User
from app.services.audit import audit
from app.services.integrations import get_nextcloud_settings

#: Above this many linked accounts, refuse a sweep that would deactivate more
#: than `_MAX_SHRINK_RATIO` of them. Below it, a ratio says nothing useful --
#: one person leaving a team of three is 33% -- and a wrong call there is
#: cheap to spot and reverse.
_RATIO_GUARD_MIN_ACCOUNTS = 10
_MAX_SHRINK_RATIO = 0.30


def _as_enabled(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"true", "1", "yes", "y", "on"}
    if isinstance(value, (int, float)):
        return bool(value)
    return True


@dataclass(frozen=True)
class SyncUser:
    nc_user_id: str
    name: str
    email: str | None
    enabled: bool


def get_nextcloud_client(db: Session | None = None) -> NextcloudOCSClient:
    values = None
    if db is not None:
        values = get_nextcloud_settings(db)
    settings = get_settings()
    values = values or {
        "url": settings.nextcloud_url,
        "admin_user": settings.nextcloud_admin_user,
        "app_password": settings.nextcloud_app_password,
        "ocs_version": settings.nextcloud_ocs_version,
        "timeout_s": settings.nextcloud_timeout_s,
        "page_size": settings.nextcloud_page_size,
    }
    cfg = NextcloudConfig(
        base_url=str(values["url"]),
        admin_user=str(values["admin_user"]),
        app_password=str(values["app_password"]),
        ocs_version=str(values["ocs_version"]),
        timeout_s=int(values["timeout_s"]),
        page_size=int(values["page_size"]),
    )
    return NextcloudOCSClient(cfg)


def fetch_nextcloud_users(client: NextcloudOCSClient) -> list[SyncUser]:
    rows: list[SyncUser] = []
    for user_id in client.list_users():
        info = client.user_info(user_id)
        display = str(info.get("displayname") or "").strip()
        email_raw = str(info.get("email") or "").strip()
        rows.append(
            SyncUser(
                nc_user_id=user_id,
                name=display or user_id,
                email=email_raw or None,
                enabled=_as_enabled(info.get("enabled")),
            )
        )
    return rows


def sync_nextcloud_person_parties(
    db: Session,
    client: NextcloudOCSClient | None = None,
    *,
    force: bool = False,
) -> dict[str, int]:
    stored = get_nextcloud_settings(db)
    enabled = bool(stored["enabled"])
    if not enabled and not force:
        return {
            "synced": 0, "created": 0, "updated": 0, "deactivated": 0,
            "disabled_or_missing": 0, "users_created": 0, "users_updated": 0,
            "users_deactivated": 0, "skipped_no_email": 0, "email_conflicts": 0,
        }
    if not stored["url"] or not stored["admin_user"] or not stored["app_password"]:
        raise RuntimeError("Nextcloud sync is enabled but credentials are missing.")

    nc = client or get_nextcloud_client(db)
    users = fetch_nextcloud_users(nc)
    active_users = [u for u in users if u.enabled]
    active_ids = {u.nc_user_id for u in active_users}
    created = 0
    updated = 0

    for user in active_users:
        row = db.scalar(select(Party).where(Party.nc_user_id == user.nc_user_id))

        if row is None and user.email:
            # One-time fallback link by email for person parties not yet linked.
            row = db.scalar(
                select(Party)
                .where(
                    Party.party_type == PartyType.PERSON,
                    Party.nc_user_id.is_(None),
                    Party.email == user.email,
                )
                .order_by(Party.id.asc())
            )

        if row is None:
            row = Party(
                party_type=PartyType.PERSON,
                name=user.name,
                email=user.email,
                is_active=True,
                nc_user_id=user.nc_user_id,
            )
            db.add(row)
            created += 1
            continue

        row.party_type = PartyType.PERSON
        row.nc_user_id = user.nc_user_id
        row.name = user.name
        row.email = user.email
        row.is_active = True
        updated += 1

    # Phase B needs the party ids that phase A just created.
    db.flush()
    user_stats = _provision_member_users(db, active_users)

    to_deactivate = db.scalars(
        select(Party).where(
            Party.party_type == PartyType.PERSON,
            Party.nc_user_id.is_not(None),
        )
    ).all()

    deactivated = 0
    users_deactivated = 0
    if _deactivation_is_safe(active_ids, list(to_deactivate)):
        for party in to_deactivate:
            if party.nc_user_id in active_ids or not party.is_active:
                continue
            party.is_active = False
            deactivated += 1
            # Only ever deactivate a member login. A staff account that happens
            # to be linked to this party keeps working -- an integration must
            # not be able to lock an administrator out.
            for linked in party.users:
                if linked.role == Role.MEMBER and linked.is_active:
                    linked.is_active = False
                    users_deactivated += 1
    else:
        audit(
            db,
            entity="nextcloud_sync",
            action="nc_sync_aborted_suspicious_shrink",
            actor_user_id=None,
            after={"active_upstream": len(active_ids), "linked_parties": len(to_deactivate)},
        )

    db.commit()
    return {
        "synced": len(active_users),
        "created": created,
        "updated": updated,
        "deactivated": deactivated,
        "disabled_or_missing": len(users) - len(active_users),
        "users_deactivated": users_deactivated,
        **user_stats,
    }


def _deactivation_is_safe(active_ids: set[str], linked: list[Party]) -> bool:
    """Guard against a truncated upstream response deactivating everyone.

    `NextcloudOCSClient.list_users` pages until it gets an empty batch, so a
    truncated or empty response is indistinguishable from "there are no more
    users" -- it does not raise. That already risked silently deactivating
    parties; now that a party carries a login, it would lock every member out
    of the system at once.

    The empty response is the catastrophic case and is always refused. The
    ratio only applies once there are enough accounts for a proportion to mean
    anything.
    """
    currently_active = [party for party in linked if party.is_active]
    if not currently_active:
        return True
    if not active_ids:
        return False
    would_deactivate = sum(1 for party in currently_active if party.nc_user_id not in active_ids)
    if len(currently_active) < _RATIO_GUARD_MIN_ACCOUNTS:
        return True
    return (would_deactivate / len(currently_active)) <= _MAX_SHRINK_RATIO


def _provision_member_users(db: Session, active_users: list[SyncUser]) -> dict[str, int]:
    """Give each active Nextcloud account an RMS login.

    Nextcloud is the identity provider, so the address written here is the same
    one `provision_oidc_preapproved_user` matches on at login -- a synced
    account can sign in without any further step.

    Role is set exactly once, at creation. A staff member who also happens to
    be a Nextcloud user keeps their role forever; this must never demote
    anyone.
    """
    created = updated = skipped = conflicts = 0
    default_language = get_default_language()

    for entry in active_users:
        email = (entry.email or "").strip().lower()
        if not email:
            # OIDC matches on email, so an account without one cannot be given
            # a working login. Counted rather than hidden.
            skipped += 1
            continue

        party = db.scalar(select(Party).where(Party.nc_user_id == entry.nc_user_id))
        if party is None:
            skipped += 1
            continue

        user = db.scalar(select(User).where(User.party_id == party.id))
        if user is None:
            user = db.scalar(select(User).where(User.nc_user_id == entry.nc_user_id))
        if user is None:
            user = db.scalar(select(User).where(func.lower(User.email) == email))

        if user is None:
            db.add(
                User(
                    email=email,
                    display_name=entry.name,
                    role=Role.MEMBER,
                    preferred_language=default_language,
                    is_active=True,
                    party_id=party.id,
                    nc_user_id=entry.nc_user_id,
                )
            )
            created += 1
            continue

        if user.email.lower() != email:
            holder = db.scalar(select(User).where(func.lower(User.email) == email))
            if holder is not None and holder.id != user.id:
                # Never steal an address off another account. Surface it and
                # leave both rows alone.
                audit(
                    db,
                    entity=user,
                    action="nc_user_email_conflict",
                    actor_user_id=None,
                    before={"email": user.email},
                    after={"nextcloud_email": email, "held_by_user_id": holder.id},
                )
                conflicts += 1
            else:
                user.email = email

        user.party_id = party.id
        user.nc_user_id = entry.nc_user_id
        user.display_name = entry.name or user.display_name
        if user.role == Role.MEMBER:
            # Reactivating a member is safe; reactivating staff is not this
            # integration's call.
            user.is_active = True
        updated += 1

    return {
        "users_created": created,
        "users_updated": updated,
        "skipped_no_email": skipped,
        "email_conflicts": conflicts,
    }
