from __future__ import annotations

from pydantic import BaseModel, Field
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.deps import require_role, verify_csrf
from app.db.session import get_db
from app.models.enums import Role
from app.models.user import User
from app.services.audit import audit
from app.services.integrations import get_nextcloud_settings, update_nextcloud_settings
from app.services.party_sync import sync_nextcloud_person_parties

router = APIRouter(prefix="/admin/integrations", tags=["admin-integrations"])


class NextcloudSettingsRead(BaseModel):
    enabled: bool
    url: str
    admin_user: str
    has_app_password: bool
    ocs_version: str
    timeout_s: int
    page_size: int


class NextcloudSettingsUpdate(BaseModel):
    enabled: bool
    url: str
    admin_user: str
    app_password: str | None = None
    ocs_version: str = "v2"
    timeout_s: int = Field(default=30, ge=1, le=300)
    page_size: int = Field(default=100, ge=1, le=1000)


@router.get("/nextcloud", response_model=NextcloudSettingsRead)
def get_nextcloud_integration(
    _: User = Depends(require_role(Role.SUPER_ADMIN, Role.ADMIN)),
    db: Session = Depends(get_db),
):
    values = get_nextcloud_settings(db)
    return NextcloudSettingsRead(
        enabled=bool(values["enabled"]),
        url=str(values["url"]),
        admin_user=str(values["admin_user"]),
        has_app_password=bool(values["app_password"]),
        ocs_version=str(values["ocs_version"]),
        timeout_s=int(values["timeout_s"]),
        page_size=int(values["page_size"]),
    )


@router.patch("/nextcloud", response_model=NextcloudSettingsRead, dependencies=[Depends(verify_csrf)])
def patch_nextcloud_integration(
    payload: NextcloudSettingsUpdate,
    actor: User = Depends(require_role(Role.SUPER_ADMIN, Role.ADMIN)),
    db: Session = Depends(get_db),
):
    values = update_nextcloud_settings(
        db,
        enabled=payload.enabled,
        url=payload.url,
        admin_user=payload.admin_user,
        app_password=payload.app_password,
        ocs_version=payload.ocs_version,
        timeout_s=payload.timeout_s,
        page_size=payload.page_size,
        actor_user_id=actor.id,
    )
    return NextcloudSettingsRead(
        enabled=bool(values["enabled"]),
        url=str(values["url"]),
        admin_user=str(values["admin_user"]),
        has_app_password=bool(values["app_password"]),
        ocs_version=str(values["ocs_version"]),
        timeout_s=int(values["timeout_s"]),
        page_size=int(values["page_size"]),
    )


@router.post("/nextcloud/sync-now", dependencies=[Depends(verify_csrf)])
def sync_nextcloud_now(
    actor: User = Depends(require_role(Role.SUPER_ADMIN, Role.ADMIN)),
    db: Session = Depends(get_db),
):
    try:
        stats = sync_nextcloud_person_parties(db, force=True)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Sync failed: {exc}") from exc
    audit(
        db,
        entity="integration",
        entity_id=None,
        action="synced",
        actor_user_id=actor.id,
        after={"key": "nextcloud", "stats": stats},
    )
    db.commit()
    return {"ok": True, "stats": stats}
