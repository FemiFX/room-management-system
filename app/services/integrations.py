from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.integration_setting import IntegrationSetting
from app.services.audit import audit

NEXTCLOUD_SETTING_KEYS = {
    "enabled": "nextcloud.enabled",
    "url": "nextcloud.url",
    "admin_user": "nextcloud.admin_user",
    "app_password": "nextcloud.app_password",
    "ocs_version": "nextcloud.ocs_version",
    "timeout_s": "nextcloud.timeout_s",
    "page_size": "nextcloud.page_size",
}


def _get_raw(db: Session, key: str) -> str | None:
    row = db.scalar(select(IntegrationSetting).where(IntegrationSetting.key == key))
    return row.value if row else None


def _set_raw(db: Session, key: str, value: str) -> None:
    row = db.scalar(select(IntegrationSetting).where(IntegrationSetting.key == key))
    if row is None:
        db.add(IntegrationSetting(key=key, value=value))
        return
    row.value = value


def get_nextcloud_settings(db: Session) -> dict[str, str | int | bool]:
    env = get_settings()

    def as_bool(v: str | None, default: bool) -> bool:
        if v is None:
            return default
        return v.strip().lower() in {"1", "true", "yes", "y", "on"}

    def as_int(v: str | None, default: int) -> int:
        if v is None:
            return default
        try:
            return int(v)
        except ValueError:
            return default

    return {
        "enabled": as_bool(_get_raw(db, NEXTCLOUD_SETTING_KEYS["enabled"]), env.nextcloud_sync_enabled),
        "url": _get_raw(db, NEXTCLOUD_SETTING_KEYS["url"]) or env.nextcloud_url,
        "admin_user": _get_raw(db, NEXTCLOUD_SETTING_KEYS["admin_user"]) or env.nextcloud_admin_user,
        "app_password": _get_raw(db, NEXTCLOUD_SETTING_KEYS["app_password"]) or env.nextcloud_app_password,
        "ocs_version": _get_raw(db, NEXTCLOUD_SETTING_KEYS["ocs_version"]) or env.nextcloud_ocs_version,
        "timeout_s": as_int(_get_raw(db, NEXTCLOUD_SETTING_KEYS["timeout_s"]), env.nextcloud_timeout_s),
        "page_size": as_int(_get_raw(db, NEXTCLOUD_SETTING_KEYS["page_size"]), env.nextcloud_page_size),
    }


def _redacted_nextcloud_snapshot(values: dict[str, str | int | bool]) -> dict:
    snapshot = dict(values)
    snapshot["app_password"] = "***" if values.get("app_password") else None
    return snapshot


def update_nextcloud_settings(
    db: Session,
    *,
    enabled: bool,
    url: str,
    admin_user: str,
    app_password: str | None,
    ocs_version: str,
    timeout_s: int,
    page_size: int,
    actor_user_id: int | None = None,
) -> dict[str, str | int | bool]:
    before = _redacted_nextcloud_snapshot(get_nextcloud_settings(db))

    _set_raw(db, NEXTCLOUD_SETTING_KEYS["enabled"], "true" if enabled else "false")
    _set_raw(db, NEXTCLOUD_SETTING_KEYS["url"], url.strip())
    _set_raw(db, NEXTCLOUD_SETTING_KEYS["admin_user"], admin_user.strip())
    if app_password is not None and app_password != "":
        _set_raw(db, NEXTCLOUD_SETTING_KEYS["app_password"], app_password)
    _set_raw(db, NEXTCLOUD_SETTING_KEYS["ocs_version"], ocs_version.strip() or "v2")
    _set_raw(db, NEXTCLOUD_SETTING_KEYS["timeout_s"], str(timeout_s))
    _set_raw(db, NEXTCLOUD_SETTING_KEYS["page_size"], str(page_size))

    db.flush()
    after = _redacted_nextcloud_snapshot(get_nextcloud_settings(db))
    audit(
        db,
        entity="integration",
        entity_id=None,
        action="updated",
        actor_user_id=actor_user_id,
        before={"key": "nextcloud", **before},
        after={"key": "nextcloud", **after},
    )
    db.commit()
    return get_nextcloud_settings(db)

