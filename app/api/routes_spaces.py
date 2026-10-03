from __future__ import annotations

from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_role, verify_csrf
from app.db.session import get_db
from app.models.building import Building
from app.models.enums import Role
from app.models.floor import Floor
from app.models.room import Room
from app.models.user import User
from app.schemas.domain import (
    BuildingCreate,
    BuildingRead,
    BuildingUpdate,
    FloorCreate,
    FloorRead,
    FloorUpdate,
    RoomCreate,
    RoomRead,
    RoomStatusRead,
    RoomUpdate,
)
from app.services.audit import audit
from app.services.business_rules import compute_room_status

router = APIRouter(tags=["spaces"])


def _building_snapshot(row: Building) -> dict:
    return {
        "name": row.name,
        "street": row.street,
        "postal_code": row.postal_code,
        "city": row.city,
        "notes": row.notes,
    }


def _floor_snapshot(row: Floor) -> dict:
    return {
        "building_id": row.building_id,
        "name": row.name,
        "floor_number": row.floor_number,
        "floorplan_object_key": row.floorplan_object_key,
        "image_object_key": row.image_object_key,
        "notes": row.notes,
    }


def _decimal(value: Decimal | None) -> str | None:
    return str(value) if value is not None else None


def _room_snapshot(row: Room) -> dict:
    return {
        "floor_id": row.floor_id,
        "room_code": row.room_code,
        "name": row.name,
        "length_m": _decimal(row.length_m),
        "width_m": _decimal(row.width_m),
        "height_m": _decimal(row.height_m),
        "area_sqm": _decimal(row.area_sqm),
        "usage_type": row.usage_type,
        "occupancy_mode": row.occupancy_mode.value,
        "rentable": row.rentable,
        "bookable": row.bookable,
        "is_active": row.is_active,
        "meter_number": row.meter_number,
        "has_internet": row.has_internet,
    }


@router.get("/buildings", response_model=list[BuildingRead])
def list_buildings(
    _: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return list(db.scalars(select(Building).order_by(Building.id.asc())).all())


@router.post("/buildings", response_model=BuildingRead, status_code=201, dependencies=[Depends(verify_csrf)])
def create_building(
    payload: BuildingCreate,
    actor: User = Depends(require_role(Role.SUPER_ADMIN, Role.ADMIN, Role.EDITOR)),
    db: Session = Depends(get_db),
):
    row = Building(**payload.model_dump())
    db.add(row)
    db.flush()
    audit(db, entity=row, action="created", actor_user_id=actor.id, after=_building_snapshot(row))
    db.commit()
    db.refresh(row)
    return row


@router.patch("/buildings/{building_id}", response_model=BuildingRead, dependencies=[Depends(verify_csrf)])
def update_building(
    building_id: int,
    payload: BuildingUpdate,
    actor: User = Depends(require_role(Role.SUPER_ADMIN, Role.ADMIN, Role.EDITOR)),
    db: Session = Depends(get_db),
):
    row = db.get(Building, building_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Building not found.")
    before = _building_snapshot(row)
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(row, key, value)
    audit(db, entity=row, action="updated", actor_user_id=actor.id, before=before, after=_building_snapshot(row))
    db.commit()
    db.refresh(row)
    return row


@router.delete("/buildings/{building_id}", status_code=204, dependencies=[Depends(verify_csrf)])
def delete_building(
    building_id: int,
    actor: User = Depends(require_role(Role.SUPER_ADMIN, Role.ADMIN)),
    db: Session = Depends(get_db),
):
    row = db.get(Building, building_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Building not found.")
    before = _building_snapshot(row)
    audit(db, entity="building", entity_id=row.id, action="deleted", actor_user_id=actor.id, before=before)
    db.delete(row)
    db.commit()


@router.get("/floors", response_model=list[FloorRead])
def list_floors(
    building_id: int | None = None,
    _: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    stmt = select(Floor)
    if building_id is not None:
        stmt = stmt.where(Floor.building_id == building_id)
    stmt = stmt.order_by(Floor.floor_number.asc(), Floor.id.asc())
    return list(db.scalars(stmt).all())


@router.post("/floors", response_model=FloorRead, status_code=201, dependencies=[Depends(verify_csrf)])
def create_floor(
    payload: FloorCreate,
    actor: User = Depends(require_role(Role.SUPER_ADMIN, Role.ADMIN, Role.EDITOR)),
    db: Session = Depends(get_db),
):
    if db.get(Building, payload.building_id) is None:
        raise HTTPException(status_code=404, detail="Building not found.")
    row = Floor(**payload.model_dump())
    db.add(row)
    try:
        db.flush()
        audit(db, entity=row, action="created", actor_user_id=actor.id, after=_floor_snapshot(row))
        db.commit()
    except Exception as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail="Floor could not be created.") from exc
    db.refresh(row)
    return row


@router.patch("/floors/{floor_id}", response_model=FloorRead, dependencies=[Depends(verify_csrf)])
def update_floor(
    floor_id: int,
    payload: FloorUpdate,
    actor: User = Depends(require_role(Role.SUPER_ADMIN, Role.ADMIN, Role.EDITOR)),
    db: Session = Depends(get_db),
):
    row = db.get(Floor, floor_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Floor not found.")
    before = _floor_snapshot(row)
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(row, key, value)
    try:
        audit(db, entity=row, action="updated", actor_user_id=actor.id, before=before, after=_floor_snapshot(row))
        db.commit()
    except Exception as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail="Floor could not be updated.") from exc
    db.refresh(row)
    return row


@router.delete("/floors/{floor_id}", status_code=204, dependencies=[Depends(verify_csrf)])
def delete_floor(
    floor_id: int,
    actor: User = Depends(require_role(Role.SUPER_ADMIN, Role.ADMIN)),
    db: Session = Depends(get_db),
):
    row = db.get(Floor, floor_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Floor not found.")
    before = _floor_snapshot(row)
    audit(db, entity="floor", entity_id=row.id, action="deleted", actor_user_id=actor.id, before=before)
    db.delete(row)
    db.commit()


@router.get("/rooms", response_model=list[RoomRead])
def list_rooms(
    _: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return list(db.scalars(select(Room).order_by(Room.room_code.asc())).all())


@router.post("/rooms", response_model=RoomRead, status_code=201, dependencies=[Depends(verify_csrf)])
def create_room(
    payload: RoomCreate,
    actor: User = Depends(require_role(Role.SUPER_ADMIN, Role.ADMIN, Role.EDITOR)),
    db: Session = Depends(get_db),
):
    if db.get(Floor, payload.floor_id) is None:
        raise HTTPException(status_code=404, detail="Floor not found.")
    row = Room(**payload.model_dump())
    db.add(row)
    try:
        db.flush()
        audit(db, entity=row, action="created", actor_user_id=actor.id, after=_room_snapshot(row))
        db.commit()
    except Exception as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail="Room could not be created.") from exc
    db.refresh(row)
    return row


@router.get("/rooms/{room_id}", response_model=RoomRead)
def get_room(
    room_id: int,
    _: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    row = db.get(Room, room_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Room not found.")
    return row


@router.patch("/rooms/{room_id}", response_model=RoomRead, dependencies=[Depends(verify_csrf)])
def update_room(
    room_id: int,
    payload: RoomUpdate,
    actor: User = Depends(require_role(Role.SUPER_ADMIN, Role.ADMIN, Role.EDITOR)),
    db: Session = Depends(get_db),
):
    row = db.get(Room, room_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Room not found.")
    before = _room_snapshot(row)
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(row, key, value)
    try:
        audit(db, entity=row, action="updated", actor_user_id=actor.id, before=before, after=_room_snapshot(row))
        db.commit()
    except Exception as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail="Room could not be updated.") from exc
    db.refresh(row)
    return row


@router.get("/rooms/{room_id}/status", response_model=RoomStatusRead)
def get_room_status(
    room_id: int,
    _: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    room = db.get(Room, room_id)
    if room is None:
        raise HTTPException(status_code=404, detail="Room not found.")
    return RoomStatusRead(room_id=room.id, status=compute_room_status(db, room))
