from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.core.templating import templates
from app.db.session import get_db
from app.models.internet_connection import InternetConnection
from app.models.key import Key, KeyAssignment
from app.models.room import Room
from app.services.business_rules import key_assignments_requiring_recovery
from app.views.deps import base_admin_context, get_authenticated_user

router = APIRouter()


@router.get("/keys", response_class=HTMLResponse)
def keys_list(request: Request, db: Session = Depends(get_db)):
    user = get_authenticated_user(request, db)
    if not user:
        return RedirectResponse(url="/auth/login", status_code=303)

    keys = (
        db.execute(
            select(Key)
            .options(joinedload(Key.room))
            .order_by(Key.key_code)
        )
        .scalars()
        .all()
    )
    rooms = db.scalars(select(Room).order_by(Room.room_code.asc())).all()

    # All currently assigned/open assignments
    assigned = db.scalars(
        select(KeyAssignment)
        .options(
            joinedload(KeyAssignment.key),
            joinedload(KeyAssignment.party),
            joinedload(KeyAssignment.room),
        )
        .where(KeyAssignment.returned_at.is_(None))
        .order_by(KeyAssignment.issued_at.asc())
    ).all()
    recovery_required = key_assignments_requiring_recovery(db)
    for assignment in recovery_required:
        reason = getattr(assignment, "recovery_reason", "")
        if reason == "inactive_person":
            setattr(assignment, "recovery_reason_text", "Inactive synced user")
        elif reason == "lease_expired":
            setattr(assignment, "recovery_reason_text", "Lease expired")
        else:
            setattr(assignment, "recovery_reason_text", "Recovery required")
    total_key_units = sum(key.total_quantity for key in keys)
    available_key_units = sum(key.available_quantity for key in keys)
    assigned_key_units = total_key_units - available_key_units
    location_totals: dict[str, int] = {}
    for key in keys:
        if key.available_quantity <= 0:
            continue
        location = (key.hanging_location or "Unspecified").strip() or "Unspecified"
        location_totals[location] = location_totals.get(location, 0) + key.available_quantity
    hanging_summary = sorted(location_totals.items(), key=lambda item: item[0].lower())

    ctx = base_admin_context(
        request, user, db, active_path="/keys",
        keys=list(keys),
        assigned=list(assigned),
        recovery_required=list(recovery_required),
        total_key_units=total_key_units,
        available_key_units=available_key_units,
        assigned_key_units=assigned_key_units,
        hanging_summary=hanging_summary,
        rooms=list(rooms),
    )
    return templates.TemplateResponse(request, "admin/keys/list.html", ctx)


@router.get("/infrastructure", response_class=HTMLResponse)
def infrastructure_page(request: Request, db: Session = Depends(get_db)):
    user = get_authenticated_user(request, db)
    if not user:
        return RedirectResponse(url="/auth/login", status_code=303)

    connections = db.scalars(
        select(InternetConnection)
        .options(joinedload(InternetConnection.room))
        .order_by(InternetConnection.room_id)
    ).all()

    rooms_with_meter = db.scalars(
        select(Room)
        .where(Room.meter_number.is_not(None))
        .order_by(Room.room_code)
    ).all()

    ctx = base_admin_context(
        request, user, db, active_path="/infrastructure",
        connections=list(connections),
        rooms_with_meter=list(rooms_with_meter),
    )
    return templates.TemplateResponse(request, "admin/infrastructure.html", ctx)
