"""Listing thumbnails for buildings and rooms.

Separate from `routes_documents` on purpose: a thumbnail is not a document.
It has no type, no lease, no audit trail of its own beyond the parent row,
and it is replaced rather than versioned. It does share the same object
storage, so nothing new has to be provisioned.
"""

from __future__ import annotations

from typing import Literal
from uuid import uuid4

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.api.deps import require_role, verify_csrf
from app.core.config import get_settings
from app.db.session import get_db
from app.models.building import Building
from app.models.enums import Role
from app.models.room import Room
from app.models.user import User
from app.services.audit import audit
from app.storage.minio_client import delete_object, get_presigned_url, upload_bytes

router = APIRouter(tags=["thumbnails"])

_WRITE_ROLES = (Role.SUPER_ADMIN, Role.ADMIN, Role.EDITOR)

#: Only formats a browser renders inline. A PDF or a TIFF would upload happily
#: and then show as a broken image in every card.
_ALLOWED = {
    "image/jpeg": "jpg",
    "image/png": "png",
    "image/webp": "webp",
    "image/avif": "avif",
}

#: Thumbnails are decoration; 8 MB is already generous for one.
_MAX_BYTES = 8 * 1024 * 1024

_MODELS = {"buildings": Building, "rooms": Room}


#: Constrained so FastAPI rejects anything else with a 422 before the handler
#: runs, rather than this route swallowing every /api/v1/<x>/<n>/thumbnail.
ListingKind = Literal["buildings", "rooms"]


def _load(db: Session, kind: str, row_id: int):
    row = db.get(_MODELS[kind], row_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Not found.")
    return row


@router.post("/{kind}/{row_id}/thumbnail", status_code=201, dependencies=[Depends(verify_csrf)])
async def upload_thumbnail(
    kind: ListingKind,
    row_id: int,
    file: UploadFile = File(...),
    actor: User = Depends(require_role(*_WRITE_ROLES)),
    db: Session = Depends(get_db),
):
    row = _load(db, kind, row_id)

    suffix = _ALLOWED.get((file.content_type or "").lower())
    if suffix is None:
        raise HTTPException(status_code=400, detail="Use a JPEG, PNG, WebP or AVIF image.")

    blob = await file.read()
    if not blob:
        raise HTTPException(status_code=400, detail="That file is empty.")
    if len(blob) > _MAX_BYTES:
        raise HTTPException(status_code=400, detail="That image is larger than 8 MB.")

    previous = row.image_object_key
    object_key = f"thumbnails/{kind}/{row_id}/{uuid4().hex}.{suffix}"
    upload_bytes(object_key=object_key, data=blob, content_type=file.content_type)

    row.image_object_key = object_key
    db.flush()
    audit(
        db, entity=row, action="updated", actor_user_id=actor.id,
        before={"image_object_key": previous}, after={"image_object_key": object_key},
    )
    db.commit()

    # Best effort: a leftover object costs storage, a failed request costs the
    # user their upload. Delete the old one only once the new one is committed.
    if previous:
        try:
            delete_object(object_key=previous)
        except Exception:  # noqa: BLE001 - storage cleanup must not fail the request
            pass

    settings = get_settings()
    return {
        "object_key": object_key,
        "url": get_presigned_url(
            object_key=object_key, expiry_seconds=settings.document_url_expire_seconds
        ),
    }


@router.delete("/{kind}/{row_id}/thumbnail", status_code=204, dependencies=[Depends(verify_csrf)])
def delete_thumbnail(
    kind: ListingKind,
    row_id: int,
    actor: User = Depends(require_role(*_WRITE_ROLES)),
    db: Session = Depends(get_db),
):
    row = _load(db, kind, row_id)
    previous = row.image_object_key
    if not previous:
        return None

    row.image_object_key = None
    db.flush()
    audit(
        db, entity=row, action="updated", actor_user_id=actor.id,
        before={"image_object_key": previous}, after={"image_object_key": None},
    )
    db.commit()
    try:
        delete_object(object_key=previous)
    except Exception:  # noqa: BLE001
        pass
    return None
