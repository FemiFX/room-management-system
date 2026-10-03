from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_role, verify_csrf
from app.db.session import get_db
from app.models.enums import LeaseStatus, Role
from app.models.internal_room_assignment import InternalRoomAssignment
from app.models.lease import Lease
from app.models.party import Party
from app.models.room import Room
from app.models.user import User
from app.schemas.domain import (
    LeaseCreate,
    LeaseRead,
    LeaseUpdate,
    InternalRoomAssignmentCreate,
    InternalRoomAssignmentEnd,
    InternalRoomAssignmentRead,
    PartyCreate,
    PartyRead,
    PartyUpdate,
)
from app.services.audit import audit
from app.services.business_rules import (
    ensure_no_active_internal_assignment_overlap,
    ensure_no_active_lease_overlap,
    ensure_team_party_for_internal_assignment,
    validate_room_can_have_internal_assignment,
    validate_room_can_have_lease,
)
from app.core.time_utils import app_now

router = APIRouter(tags=["occupancy"])


def _decimal(value: Decimal | None) -> str | None:
    return str(value) if value is not None else None


def _date(value: date | None) -> str | None:
    return value.isoformat() if value is not None else None


def _datetime(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _party_snapshot(row: Party) -> dict:
    return {
        "nc_user_id": row.nc_user_id,
        "party_type": row.party_type.value,
        "name": row.name,
        "email": row.email,
        "phone": row.phone,
        "street": row.street,
        "postal_code": row.postal_code,
        "city": row.city,
        "is_active": row.is_active,
        "notes": row.notes,
    }


def _lease_snapshot(row: Lease) -> dict:
    return {
        "room_id": row.room_id,
        "party_id": row.party_id,
        "contract_reference": row.contract_reference,
        "start_date": _date(row.start_date),
        "end_date": _date(row.end_date),
        "notice_period_days": row.notice_period_days,
        "monthly_rent": _decimal(row.monthly_rent),
        "deposit_amount": _decimal(row.deposit_amount),
        "currency": row.currency,
        "status": row.status.value,
        "notes": row.notes,
    }


def _internal_assignment_snapshot(row: InternalRoomAssignment) -> dict:
    return {
        "room_id": row.room_id,
        "party_id": row.party_id,
        "assigned_by_user_id": row.assigned_by_user_id,
        "start_date": _date(row.start_date),
        "end_date": _date(row.end_date),
        "notes": row.notes,
    }


@router.get("/parties", response_model=list[PartyRead])
def list_parties(
    _: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return list(db.scalars(select(Party).order_by(Party.id.asc())).all())


@router.post("/parties", response_model=PartyRead, status_code=201, dependencies=[Depends(verify_csrf)])
def create_party(
    payload: PartyCreate,
    actor: User = Depends(require_role(Role.SUPER_ADMIN, Role.ADMIN, Role.EDITOR)),
    db: Session = Depends(get_db),
):
    cutoff = app_now() - timedelta(minutes=2)
    existing_recent = db.scalar(
        select(Party)
        .where(
            Party.party_type == payload.party_type,
            func.lower(Party.name) == payload.name.strip().lower(),
            func.coalesce(func.lower(Party.email), "") == (payload.email or "").strip().lower(),
            func.coalesce(Party.phone, "") == (payload.phone or "").strip(),
            func.coalesce(Party.notes, "") == (payload.notes or "").strip(),
            Party.created_at >= cutoff,
        )
        .order_by(Party.created_at.desc())
    )
    if existing_recent is not None:
        raise HTTPException(status_code=409, detail="A matching party was just created. Please refresh before retrying.")

    row = Party(**payload.model_dump())
    db.add(row)
    db.flush()
    audit(db, entity=row, action="created", actor_user_id=actor.id, after=_party_snapshot(row))
    db.commit()
    db.refresh(row)
    return row


@router.patch("/parties/{party_id}", response_model=PartyRead, dependencies=[Depends(verify_csrf)])
def update_party(
    party_id: int,
    payload: PartyUpdate,
    actor: User = Depends(require_role(Role.SUPER_ADMIN, Role.ADMIN, Role.EDITOR)),
    db: Session = Depends(get_db),
):
    row = db.get(Party, party_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Party not found.")
    before = _party_snapshot(row)
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(row, key, value)
    audit(db, entity=row, action="updated", actor_user_id=actor.id, before=before, after=_party_snapshot(row))
    db.commit()
    db.refresh(row)
    return row


@router.delete("/parties/{party_id}", status_code=204, dependencies=[Depends(verify_csrf)])
def delete_party(
    party_id: int,
    actor: User = Depends(require_role(Role.SUPER_ADMIN, Role.ADMIN)),
    db: Session = Depends(get_db),
):
    row = db.get(Party, party_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Party not found.")
    before = _party_snapshot(row)
    audit(db, entity="party", entity_id=row.id, action="deleted", actor_user_id=actor.id, before=before)
    db.delete(row)
    try:
        db.commit()
    except Exception as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail="Party cannot be deleted because it is still referenced.") from exc


@router.get("/leases", response_model=list[LeaseRead])
def list_leases(
    _: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return list(db.scalars(select(Lease).order_by(Lease.id.asc())).all())


@router.get("/rooms/{room_id}/internal-assignments", response_model=list[InternalRoomAssignmentRead])
def list_internal_room_assignments(
    room_id: int,
    _: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if db.get(Room, room_id) is None:
        raise HTTPException(status_code=404, detail="Room not found.")
    return list(
        db.scalars(
            select(InternalRoomAssignment)
            .where(InternalRoomAssignment.room_id == room_id)
            .order_by(InternalRoomAssignment.start_date.desc(), InternalRoomAssignment.id.desc())
        ).all()
    )


@router.post(
    "/internal-room-assignments",
    response_model=InternalRoomAssignmentRead,
    status_code=201,
    dependencies=[Depends(verify_csrf)],
)
def create_internal_room_assignment(
    payload: InternalRoomAssignmentCreate,
    current_user: User = Depends(require_role(Role.SUPER_ADMIN, Role.ADMIN, Role.EDITOR)),
    db: Session = Depends(get_db),
):
    room = db.get(Room, payload.room_id)
    if room is None:
        raise HTTPException(status_code=404, detail="Room not found.")
    try:
        validate_room_can_have_internal_assignment(room)
        ensure_team_party_for_internal_assignment(db, party_id=payload.party_id)
        ensure_no_active_internal_assignment_overlap(
            db,
            room_id=payload.room_id,
            start_date=payload.start_date,
            end_date=None,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    row = InternalRoomAssignment(
        room_id=payload.room_id,
        party_id=payload.party_id,
        assigned_by_user_id=current_user.id,
        start_date=payload.start_date,
        notes=payload.notes,
    )
    db.add(row)
    db.flush()
    audit(
        db,
        entity="internal_assignment",
        entity_id=row.id,
        action="created",
        actor_user_id=current_user.id,
        after=_internal_assignment_snapshot(row),
    )
    db.commit()
    db.refresh(row)
    return row


@router.post(
    "/internal-room-assignments/{assignment_id}/end",
    response_model=InternalRoomAssignmentRead,
    dependencies=[Depends(verify_csrf)],
)
def end_internal_room_assignment(
    assignment_id: int,
    payload: InternalRoomAssignmentEnd,
    actor: User = Depends(require_role(Role.SUPER_ADMIN, Role.ADMIN, Role.EDITOR)),
    db: Session = Depends(get_db),
):
    row = db.get(InternalRoomAssignment, assignment_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Internal assignment not found.")
    if row.end_date is not None:
        raise HTTPException(status_code=400, detail="Internal assignment is already ended.")
    if payload.end_date < row.start_date:
        raise HTTPException(status_code=400, detail="End date cannot be before start date.")

    before = _internal_assignment_snapshot(row)
    row.end_date = payload.end_date
    if payload.notes:
        row.notes = payload.notes
    audit(
        db,
        entity="internal_assignment",
        entity_id=row.id,
        action="ended",
        actor_user_id=actor.id,
        before=before,
        after=_internal_assignment_snapshot(row),
    )
    db.commit()
    db.refresh(row)
    return row


@router.post("/leases", response_model=LeaseRead, status_code=201, dependencies=[Depends(verify_csrf)])
def create_lease(
    payload: LeaseCreate,
    actor: User = Depends(require_role(Role.SUPER_ADMIN, Role.ADMIN, Role.EDITOR)),
    db: Session = Depends(get_db),
):
    room = db.get(Room, payload.room_id)
    if room is None:
        raise HTTPException(status_code=404, detail="Room not found.")
    party = db.get(Party, payload.party_id)
    if party is None:
        raise HTTPException(status_code=404, detail="Party not found.")
    if party.nc_user_id:
        raise HTTPException(status_code=400, detail="Leases cannot be assigned to internal synced parties.")

    try:
        validate_room_can_have_lease(room)
        if payload.status == LeaseStatus.ACTIVE:
            ensure_no_active_lease_overlap(
                db,
                room_id=payload.room_id,
                start_date=payload.start_date,
                end_date=payload.end_date,
            )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    row = Lease(**payload.model_dump())
    db.add(row)
    db.flush()
    audit(db, entity=row, action="created", actor_user_id=actor.id, after=_lease_snapshot(row))
    db.commit()
    db.refresh(row)
    return row


@router.patch("/leases/{lease_id}", response_model=LeaseRead, dependencies=[Depends(verify_csrf)])
def update_lease(
    lease_id: int,
    payload: LeaseUpdate,
    actor: User = Depends(require_role(Role.SUPER_ADMIN, Role.ADMIN, Role.EDITOR)),
    db: Session = Depends(get_db),
):
    row = db.get(Lease, lease_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Lease not found.")

    before = _lease_snapshot(row)
    data = payload.model_dump(exclude_unset=True)
    for key, value in data.items():
        setattr(row, key, value)

    if row.party_id:
        party = db.get(Party, row.party_id)
        if party is None:
            raise HTTPException(status_code=404, detail="Party not found.")
        if party.nc_user_id:
            raise HTTPException(status_code=400, detail="Leases cannot be assigned to internal synced parties.")

    room = db.get(Room, row.room_id)
    try:
        validate_room_can_have_lease(room)
        if row.status == LeaseStatus.ACTIVE:
            ensure_no_active_lease_overlap(
                db,
                room_id=row.room_id,
                start_date=row.start_date,
                end_date=row.end_date,
                exclude_lease_id=row.id,
            )
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    audit(db, entity=row, action="updated", actor_user_id=actor.id, before=before, after=_lease_snapshot(row))
    db.commit()
    db.refresh(row)
    return row
