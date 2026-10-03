from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_role, verify_csrf
from app.core.config import get_settings
from app.db.session import get_db
from app.models.document import Document
from app.models.enums import DocumentType, Role
from app.models.lease import Lease
from app.models.room import Room
from app.models.user import User
from app.schemas.domain import DocumentRead
from app.services.audit import audit
from app.storage.minio_client import delete_object, get_presigned_url, upload_bytes

router = APIRouter(tags=["documents"])


def _document_snapshot(row: Document) -> dict:
    return {
        "room_id": row.room_id,
        "lease_id": row.lease_id,
        "uploaded_by_user_id": row.uploaded_by_user_id,
        "document_type": row.document_type.value,
        "title": row.title,
        "object_key": row.object_key,
        "original_filename": row.original_filename,
        "mime_type": row.mime_type,
        "file_size": row.file_size,
        "uploaded_at": row.uploaded_at.isoformat() if row.uploaded_at else None,
        "notes": row.notes,
    }


@router.get("/documents", response_model=list[DocumentRead])
def list_documents(
    _: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return list(db.scalars(select(Document).order_by(Document.uploaded_at.desc())).all())


@router.post("/documents/upload", response_model=DocumentRead, status_code=201, dependencies=[Depends(verify_csrf)])
async def upload_document(
    title: str = Form(...),
    document_type: DocumentType = Form(...),
    room_id: int | None = Form(default=None),
    lease_id: int | None = Form(default=None),
    notes: str | None = Form(default=None),
    file: UploadFile = File(...),
    current_user: User = Depends(require_role(Role.SUPER_ADMIN, Role.ADMIN, Role.EDITOR)),
    db: Session = Depends(get_db),
):
    if room_id is not None and db.get(Room, room_id) is None:
        raise HTTPException(status_code=404, detail="Room not found.")
    if lease_id is not None and db.get(Lease, lease_id) is None:
        raise HTTPException(status_code=404, detail="Lease not found.")

    blob = await file.read()
    suffix = file.filename.split(".")[-1].lower() if file.filename and "." in file.filename else "bin"
    object_key = f"documents/{document_type.value}/{uuid4().hex}.{suffix}"
    upload_bytes(object_key=object_key, data=blob, content_type=file.content_type)

    row = Document(
        room_id=room_id,
        lease_id=lease_id,
        uploaded_by_user_id=current_user.id,
        document_type=document_type,
        title=title,
        object_key=object_key,
        original_filename=file.filename,
        mime_type=file.content_type,
        file_size=len(blob),
        uploaded_at=datetime.now(timezone.utc),
        notes=notes,
    )
    db.add(row)
    db.flush()
    audit(db, entity=row, action="uploaded", actor_user_id=current_user.id, after=_document_snapshot(row))
    db.commit()
    db.refresh(row)
    return row


@router.get("/documents/{document_id}", response_model=DocumentRead)
def get_document(
    document_id: int,
    _: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    row = db.get(Document, document_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Document not found.")
    return row


@router.get("/documents/{document_id}/url")
def get_document_url(
    document_id: int,
    _: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    row = db.get(Document, document_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Document not found.")
    settings = get_settings()
    return {"url": get_presigned_url(object_key=row.object_key, expiry_seconds=settings.document_url_expire_seconds)}


@router.delete("/documents/{document_id}", status_code=204, dependencies=[Depends(verify_csrf)])
def delete_document(
    document_id: int,
    actor: User = Depends(require_role(Role.SUPER_ADMIN, Role.ADMIN)),
    db: Session = Depends(get_db),
):
    row = db.get(Document, document_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Document not found.")
    before = _document_snapshot(row)
    delete_object(object_key=row.object_key)
    audit(db, entity="document", entity_id=row.id, action="deleted", actor_user_id=actor.id, before=before)
    db.delete(row)
    db.commit()
