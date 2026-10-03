from __future__ import annotations

from datetime import date, timedelta

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import or_, select
from sqlalchemy.orm import Session, joinedload

from app.core.templating import templates
from app.db.session import get_db
from app.models.enums import LeaseStatus
from app.models.internal_room_assignment import InternalRoomAssignment
from app.models.enums import PartyType
from app.models.lease import Lease
from app.models.party import Party
from app.views.deps import base_admin_context, get_authenticated_user

router = APIRouter()


@router.get("/parties", response_class=HTMLResponse)
def parties_list(request: Request, db: Session = Depends(get_db)):
    user = get_authenticated_user(request, db)
    if not user:
        return RedirectResponse(url="/auth/login", status_code=303)

    parties = list(db.scalars(select(Party).order_by(Party.name)).all())
    synced_people = [p for p in parties if p.party_type == PartyType.PERSON and p.nc_user_id]
    manual_people = [p for p in parties if p.party_type == PartyType.PERSON and not p.nc_user_id]
    teams = [p for p in parties if p.party_type == PartyType.TEAM]
    organizations = [p for p in parties if p.party_type == PartyType.ORGANIZATION]
    ctx = base_admin_context(
        request, user, db, active_path="/parties",
        parties=parties,
        synced_people=synced_people,
        manual_people=manual_people,
        teams=teams,
        organizations=organizations,
    )
    return templates.TemplateResponse(request, "admin/parties/list.html", ctx)


@router.get("/parties/{party_id}", response_class=HTMLResponse)
def party_detail(party_id: int, request: Request, db: Session = Depends(get_db)):
    user = get_authenticated_user(request, db)
    if not user:
        return RedirectResponse(url="/auth/login", status_code=303)

    party = db.scalar(
        select(Party)
        .options(
            joinedload(Party.leases).joinedload(Lease.room),
            joinedload(Party.key_assignments),
            joinedload(Party.internal_room_assignments).joinedload(InternalRoomAssignment.room),
        )
        .where(Party.id == party_id)
    )
    if party is None:
        return RedirectResponse(url="/parties", status_code=303)

    # Eagerly load room for key assignments
    for ka in party.key_assignments:
        _ = ka.key
        _ = ka.room
    for ia in party.internal_room_assignments:
        _ = ia.room

    ctx = base_admin_context(
        request, user, db, active_path="/parties",
        party=party,
    )
    return templates.TemplateResponse(request, "admin/parties/detail.html", ctx)


@router.get("/leases", response_class=HTMLResponse)
def leases_list(request: Request, db: Session = Depends(get_db)):
    user = get_authenticated_user(request, db)
    if not user:
        return RedirectResponse(url="/auth/login", status_code=303)

    status_filter = request.query_params.get("status", "all")
    today = date.today()

    stmt = (
        select(Lease)
        .options(
            joinedload(Lease.room),
            joinedload(Lease.party),
        )
        .order_by(Lease.start_date.desc())
    )

    if status_filter == "active":
        stmt = stmt.where(
            Lease.status == LeaseStatus.ACTIVE,
            Lease.start_date <= today,
            or_(Lease.end_date.is_(None), Lease.end_date >= today),
        )
    elif status_filter == "draft":
        stmt = stmt.where(Lease.status == LeaseStatus.DRAFT)
    elif status_filter == "expiring":
        stmt = stmt.where(
            Lease.status == LeaseStatus.ACTIVE,
            Lease.end_date.is_not(None),
            Lease.end_date <= today + timedelta(days=30),
            Lease.end_date >= today,
        )
    elif status_filter == "expired":
        stmt = stmt.where(Lease.status == LeaseStatus.EXPIRED)

    leases = list(db.scalars(stmt).all())

    # Annotate each lease with an expiring flag
    leases_annotated = []
    for lease in leases:
        is_expiring = (
            lease.status == LeaseStatus.ACTIVE
            and lease.end_date is not None
            and lease.end_date <= today + timedelta(days=30)
            and lease.end_date >= today
        )
        leases_annotated.append({"lease": lease, "is_expiring": is_expiring})

    ctx = base_admin_context(
        request, user, db, active_path="/leases",
        leases_annotated=leases_annotated,
        status_filter=status_filter,
    )
    return templates.TemplateResponse(request, "admin/leases/list.html", ctx)
