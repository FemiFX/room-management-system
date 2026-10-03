from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.core.templating import templates
from app.db.session import get_db
from app.models.document import Document
from app.models.floor import Floor
from app.models.room import Room
from app.views.deps import base_admin_context, get_authenticated_user

router = APIRouter()


@router.get("/documents", response_class=HTMLResponse)
def documents_list(request: Request, db: Session = Depends(get_db)):
    user = get_authenticated_user(request, db)
    if not user:
        return RedirectResponse(url="/auth/login", status_code=303)

    doc_type_filter = request.query_params.get("type", "all")

    stmt = (
        select(Document)
        .options(
            joinedload(Document.room),
            joinedload(Document.lease),
        )
        .order_by(Document.uploaded_at.desc())
    )
    if doc_type_filter != "all":
        stmt = stmt.where(Document.document_type == doc_type_filter)

    documents = list(db.scalars(stmt).all())

    # Grouped by room, one tab each. Every active room gets a tab even with no
    # documents, so "this room has nothing filed" is visible rather than the
    # room being missing; a leading bucket holds documents attached to a lease
    # or to nothing at all -- document.room_id is nullable and such rows exist.
    rooms = db.scalars(
        select(Room)
        .options(joinedload(Room.floor).joinedload(Floor.building))
        .where(Room.is_active.is_(True))
        .order_by(Room.room_code)
    ).unique().all()

    by_room: dict[int | None, list[Document]] = {}
    for document in documents:
        by_room.setdefault(document.room_id, []).append(document)

    room_tabs = [{"room": None, "documents": by_room.get(None, [])}]
    room_tabs += [{"room": room, "documents": by_room.get(room.id, [])} for room in rooms]

    ctx = base_admin_context(
        request, user, db, active_path="/documents",
        documents=documents,
        room_tabs=room_tabs,
        doc_type_filter=doc_type_filter,
    )
    return templates.TemplateResponse(request, "admin/documents/list.html", ctx)


@router.get("/documents/{doc_id}", response_class=HTMLResponse)
def document_detail(doc_id: int, request: Request, db: Session = Depends(get_db)):
    user = get_authenticated_user(request, db)
    if not user:
        return RedirectResponse(url="/auth/login", status_code=303)

    doc = db.scalar(
        select(Document)
        .options(joinedload(Document.room), joinedload(Document.lease))
        .where(Document.id == doc_id)
    )
    if doc is None:
        return RedirectResponse(url="/documents", status_code=303)

    ext = ""
    if doc.original_filename:
        parts = doc.original_filename.rsplit(".", 1)
        ext = parts[-1].lower() if len(parts) == 2 else ""

    size_mb = round(doc.file_size / (1024 * 1024), 2) if doc.file_size else None

    ctx = base_admin_context(
        request, user, db, active_path="/documents",
        doc=doc,
        file_ext=ext,
        file_size_mb=size_mb,
    )
    return templates.TemplateResponse(request, "admin/documents/detail.html", ctx)
