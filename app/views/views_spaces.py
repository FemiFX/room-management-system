from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.core.templating import templates
from app.db.session import get_db
from app.models.building import Building
from app.models.floor import Floor
from app.models.internal_room_assignment import InternalRoomAssignment
from app.models.room import Room
from app.services.business_rules import (
    active_internal_assignment_for_room,
    active_key_assignments_for_room,
    active_lease_for_room,
    compute_room_status,
    current_approved_booking_for_room,
    next_approved_booking_for_room,
)
from app.storage.minio_client import get_object_bytes
from app.views.deps import base_admin_context, get_authenticated_user

router = APIRouter()


def _thumb_url(kind: str, row_id: int, object_key: str | None) -> str | None:
    """URL of a listing thumbnail, or None when the row has no photo.

    Served through this app rather than as a presigned storage URL. A
    presigned URL expires (15 minutes by default) while the listing is still
    open, which would turn every card into a broken image; and in a
    container-only stack its host is not resolvable from the browser at all.
    The object key is in the path, so replacing a photo busts the cache.
    """
    if not object_key:
        return None
    return f"/thumbnails/{kind}/{row_id}?v={object_key.rsplit('/', 1)[-1]}"


def _view_mode(request: Request, default: str = "grid") -> str:
    """`?view=` decides; anything else falls back. The client also remembers
    the choice in localStorage and rewrites the query string, so a reload or a
    shared link keeps the view the user was looking at."""
    requested = request.query_params.get("view")
    return requested if requested in {"grid", "list"} else default


@router.get("/thumbnails/{kind}/{row_id}")
def thumbnail_image(kind: str, row_id: int, request: Request, db: Session = Depends(get_db)):
    """Serve a listing thumbnail to signed-in staff.

    Behind the session like every other admin page -- an object key is not a
    capability. Cached hard because the URL carries the key: a replaced photo
    is a different URL, so nothing stale can be served.
    """
    user = get_authenticated_user(request, db)
    if not user:
        return RedirectResponse(url="/auth/login", status_code=303)

    models = {"buildings": Building, "rooms": Room}
    model = models.get(kind)
    if model is None:
        raise HTTPException(status_code=404)
    row = db.get(model, row_id)
    if row is None or not row.image_object_key:
        raise HTTPException(status_code=404)

    try:
        blob, content_type = get_object_bytes(object_key=row.image_object_key)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=404) from exc

    return Response(
        content=blob,
        media_type=content_type or "application/octet-stream",
        headers={"Cache-Control": "private, max-age=86400"},
    )


@router.get("/buildings", response_class=HTMLResponse)
def buildings_list(request: Request, db: Session = Depends(get_db)):
    user = get_authenticated_user(request, db)
    if not user:
        return RedirectResponse(url="/auth/login", status_code=303)

    buildings = db.scalars(
        select(Building)
        .options(joinedload(Building.floors).joinedload(Floor.rooms))
        .order_by(Building.name)
    ).unique().all()

    buildings_data = [
        {
            "building": b,
            "floor_count": len(b.floors),
            "room_count": sum(len(f.rooms) for f in b.floors),
            "thumb_url": _thumb_url("buildings", b.id, b.image_object_key),
        }
        for b in buildings
    ]

    ctx = base_admin_context(
        request, user, db,
        active_path="/buildings",
        buildings_data=buildings_data,
        view_mode=_view_mode(request),
    )
    return templates.TemplateResponse(request, "admin/buildings/list.html", ctx)


@router.get("/rooms", response_class=HTMLResponse)
def rooms_list(request: Request, db: Session = Depends(get_db)):
    user = get_authenticated_user(request, db)
    if not user:
        return RedirectResponse(url="/auth/login", status_code=303)

    rooms = db.scalars(
        select(Room)
        .options(joinedload(Room.floor).joinedload(Floor.building))
        .order_by(Room.room_code)
    ).all()

    buildings = db.scalars(select(Building).order_by(Building.name)).all()

    rooms_with_status = [
        {
            "room": room,
            "status": compute_room_status(db, room),
            "thumb_url": _thumb_url("rooms", room.id, room.image_object_key),
        }
        for room in rooms
    ]

    ctx = base_admin_context(
        request, user, db,
        active_path="/rooms",
        rooms_with_status=rooms_with_status,
        buildings=buildings,
        view_mode=_view_mode(request),
    )
    return templates.TemplateResponse(request, "admin/rooms/list.html", ctx)


@router.get("/rooms/{room_id}", response_class=HTMLResponse)
def room_detail(room_id: int, request: Request, db: Session = Depends(get_db)):
    user = get_authenticated_user(request, db)
    if not user:
        return RedirectResponse(url="/auth/login", status_code=303)

    room = db.scalar(
        select(Room)
        .options(
            joinedload(Room.floor).joinedload(Floor.building),
            joinedload(Room.keys),
            joinedload(Room.internal_assignments).joinedload(InternalRoomAssignment.party),
            joinedload(Room.internal_assignments).joinedload(InternalRoomAssignment.assigned_by),
            joinedload(Room.room_equipment),
            joinedload(Room.internet_connections),
            joinedload(Room.documents),
        )
        .where(Room.id == room_id)
    )
    if room is None:
        return RedirectResponse(url="/rooms", status_code=303)

    status = compute_room_status(db, room)
    active_internal_assignment = active_internal_assignment_for_room(db, room.id)
    internal_assignment_history = sorted(
        room.internal_assignments,
        key=lambda item: (item.start_date, item.id),
        reverse=True,
    )
    active_lease = active_lease_for_room(db, room.id)
    current_booking = current_approved_booking_for_room(db, room.id)
    next_booking = next_approved_booking_for_room(db, room.id)
    key_assignments = active_key_assignments_for_room(db, room.id)
    room_keys = sorted(room.keys, key=lambda item: item.key_code.lower())

    # Eagerly load party for lease and key assignments
    if active_lease:
        _ = active_lease.party
    for ka in key_assignments:
        _ = ka.key
        _ = ka.party
    for ia in internal_assignment_history:
        _ = ia.party
        _ = ia.assigned_by

    ctx = base_admin_context(
        request, user, db,
        active_path="/rooms",
        room=room,
        status=status,
        active_internal_assignment=active_internal_assignment,
        internal_assignment_history=internal_assignment_history,
        active_lease=active_lease,
        current_booking=current_booking,
        next_booking=next_booking,
        key_assignments=key_assignments,
        room_keys=room_keys,
    )
    return templates.TemplateResponse(request, "admin/rooms/detail.html", ctx)
