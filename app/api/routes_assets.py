from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload

from app.api.deps import get_current_user, require_role, verify_csrf
from app.db.session import get_db
from app.models.enums import Role
from app.models.booking_request import BookingEquipmentRequest
from app.models.equipment import Equipment, RoomEquipment
from app.models.internet_connection import InternetConnection
from app.models.key import Key, KeyAssignment
from app.models.room import Room
from app.models.user import User
from app.schemas.domain import (
    EquipmentCreate,
    EquipmentUpdate,
    EquipmentRead,
    InternetConnectionCreate,
    InternetConnectionRead,
    KeyAssignmentCreate,
    KeyAssignmentRead,
    KeyAssignmentReturn,
    KeyCreate,
    KeyRead,
    KeyUpdate,
    RoomEquipmentCreate,
    RoomEquipmentUpdate,
    RoomEquipmentRead,
)
from app.services.audit import audit
from app.services.business_rules import ensure_active_party
from app.storage.minio_client import delete_object, upload_bytes

router = APIRouter(tags=["assets"])


def _datetime(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _key_snapshot(row: Key) -> dict:
    return {
        "room_id": row.room_id,
        "key_code": row.key_code,
        "description": row.description,
        "hanging_location": row.hanging_location,
        "master_key": row.master_key,
        "is_active": row.is_active,
        "total_quantity": row.total_quantity,
        "available_quantity": row.available_quantity,
    }


def _key_assignment_snapshot(row: KeyAssignment) -> dict:
    return {
        "key_id": row.key_id,
        "room_id": row.room_id,
        "party_id": row.party_id,
        "issued_at": _datetime(row.issued_at),
        "returned_at": _datetime(row.returned_at),
        "issue_note": row.issue_note,
        "issue_receipt_object_key": row.issue_receipt_object_key,
        "issue_receipt_filename": row.issue_receipt_filename,
        "issue_receipt_mime_type": row.issue_receipt_mime_type,
        "issue_receipt_size": row.issue_receipt_size,
        "return_note": row.return_note,
    }


def _equipment_snapshot(row: Equipment) -> dict:
    return {"name": row.name, "category": row.category, "notes": row.notes}


def _room_equipment_snapshot(row: RoomEquipment) -> dict:
    return {
        "room_id": row.room_id,
        "equipment_id": row.equipment_id,
        "quantity": row.quantity,
        "fixed": row.fixed,
        "notes": row.notes,
    }


def _internet_connection_snapshot(row: InternetConnection) -> dict:
    return {
        "room_id": row.room_id,
        "medium": row.medium.value,
        "channel": row.channel,
        "provider": row.provider,
        "is_active": row.is_active,
        "notes": row.notes,
    }


@router.get("/keys", response_model=list[KeyRead])
def list_keys(
    _: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return list(
        db.scalars(
            select(Key)
            .options(joinedload(Key.room))
            .order_by(Key.key_code.asc())
        ).all()
    )


@router.post("/keys", response_model=KeyRead, status_code=201, dependencies=[Depends(verify_csrf)])
def create_key(
    payload: KeyCreate,
    actor: User = Depends(require_role(Role.SUPER_ADMIN, Role.ADMIN, Role.EDITOR)),
    db: Session = Depends(get_db),
):
    data = payload.model_dump()
    if data.get("room_id") is not None and db.get(Room, data["room_id"]) is None:
        raise HTTPException(status_code=404, detail="Room not found.")
    data["available_quantity"] = data["total_quantity"]
    row = Key(**data)
    db.add(row)
    try:
        db.flush()
        audit(db, entity=row, action="created", actor_user_id=actor.id, after=_key_snapshot(row))
        db.commit()
    except Exception as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail="Key already exists.") from exc
    db.refresh(row)
    return row


@router.patch("/keys/{key_id}", response_model=KeyRead, dependencies=[Depends(verify_csrf)])
def update_key(
    key_id: int,
    payload: KeyUpdate,
    actor: User = Depends(require_role(Role.SUPER_ADMIN, Role.ADMIN, Role.EDITOR)),
    db: Session = Depends(get_db),
):
    row = db.scalar(select(Key).where(Key.id == key_id).with_for_update())
    if row is None:
        raise HTTPException(status_code=404, detail="Key not found.")

    before = _key_snapshot(row)
    data = payload.model_dump(exclude_unset=True)
    if "room_id" in data and data["room_id"] is not None and db.get(Room, data["room_id"]) is None:
        raise HTTPException(status_code=404, detail="Room not found.")
    if "total_quantity" in data:
        assigned_quantity = row.total_quantity - row.available_quantity
        new_total = data["total_quantity"]
        if new_total < assigned_quantity:
            raise HTTPException(
                status_code=400,
                detail=f"Total quantity cannot be below currently assigned quantity ({assigned_quantity}).",
            )
        row.available_quantity = new_total - assigned_quantity

    for key, value in data.items():
        setattr(row, key, value)

    try:
        audit(db, entity=row, action="updated", actor_user_id=actor.id, before=before, after=_key_snapshot(row))
        db.commit()
    except Exception as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail="Key could not be updated.") from exc
    db.refresh(row)
    return row


@router.delete("/keys/{key_id}", status_code=204, dependencies=[Depends(verify_csrf)])
def delete_key(
    key_id: int,
    actor: User = Depends(require_role(Role.SUPER_ADMIN, Role.ADMIN)),
    db: Session = Depends(get_db),
):
    row = db.scalar(select(Key).where(Key.id == key_id).with_for_update())
    if row is None:
        raise HTTPException(status_code=404, detail="Key not found.")
    if row.assignments:
        raise HTTPException(status_code=400, detail="Key cannot be deleted because assignment history exists.")
    before = _key_snapshot(row)
    audit(db, entity="key", entity_id=row.id, action="deleted", actor_user_id=actor.id, before=before)
    db.delete(row)
    db.commit()


@router.get("/key-assignments", response_model=list[KeyAssignmentRead])
def list_key_assignments(
    _: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return list(db.scalars(select(KeyAssignment).order_by(KeyAssignment.issued_at.desc())).all())


@router.post("/key-assignments", response_model=KeyAssignmentRead, status_code=201, dependencies=[Depends(verify_csrf)])
def create_key_assignment(
    payload: KeyAssignmentCreate,
    actor: User = Depends(require_role(Role.SUPER_ADMIN, Role.ADMIN, Role.EDITOR)),
    db: Session = Depends(get_db),
):
    row = _create_key_assignment_row(db=db, payload=payload)
    try:
        db.flush()
        audit(db, entity=row, action="issued", actor_user_id=actor.id, after=_key_assignment_snapshot(row))
        db.commit()
    except Exception as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail="Unable to assign key.") from exc
    db.refresh(row)
    return row


@router.post("/key-assignments/upload", response_model=KeyAssignmentRead, status_code=201, dependencies=[Depends(verify_csrf)])
async def create_key_assignment_with_receipt(
    key_id: int = Form(...),
    room_id: int = Form(...),
    party_id: int = Form(...),
    issued_at: datetime = Form(...),
    issue_note: str | None = Form(default=None),
    receipt_file: UploadFile | None = File(default=None),
    actor: User = Depends(require_role(Role.SUPER_ADMIN, Role.ADMIN, Role.EDITOR)),
    db: Session = Depends(get_db),
):
    payload = KeyAssignmentCreate(
        key_id=key_id,
        room_id=room_id,
        party_id=party_id,
        issued_at=issued_at,
        issue_note=issue_note,
    )
    row = _create_key_assignment_row(db=db, payload=payload)

    uploaded_object_key: str | None = None
    if receipt_file is not None and receipt_file.filename:
        blob = await receipt_file.read()
        suffix = receipt_file.filename.split(".")[-1].lower() if "." in receipt_file.filename else "bin"
        uploaded_object_key = f"documents/key_receipts/{uuid4().hex}.{suffix}"
        upload_bytes(object_key=uploaded_object_key, data=blob, content_type=receipt_file.content_type)
        row.issue_receipt_object_key = uploaded_object_key
        row.issue_receipt_filename = receipt_file.filename
        row.issue_receipt_mime_type = receipt_file.content_type
        row.issue_receipt_size = len(blob)

    try:
        db.flush()
        snapshot = _key_assignment_snapshot(row)
        snapshot["has_receipt"] = uploaded_object_key is not None
        audit(db, entity=row, action="issued", actor_user_id=actor.id, after=snapshot)
        db.commit()
    except Exception as exc:
        db.rollback()
        if uploaded_object_key:
            delete_object(object_key=uploaded_object_key)
        raise HTTPException(status_code=400, detail="Unable to assign key.") from exc
    db.refresh(row)
    return row


def _create_key_assignment_row(*, db: Session, payload: KeyAssignmentCreate) -> KeyAssignment:
    key = db.scalar(select(Key).where(Key.id == payload.key_id).with_for_update())
    if key is None:
        raise HTTPException(status_code=404, detail="Key not found.")
    if not key.is_active:
        raise HTTPException(status_code=400, detail="Key is deactivated.")
    if key.available_quantity <= 0:
        raise HTTPException(status_code=400, detail="No available quantity for this key.")
    if db.get(Room, payload.room_id) is None:
        raise HTTPException(status_code=404, detail="Room not found.")
    try:
        ensure_active_party(db, party_id=payload.party_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    existing_open = db.scalar(
        select(KeyAssignment).where(
            KeyAssignment.key_id == payload.key_id,
            KeyAssignment.party_id == payload.party_id,
            KeyAssignment.room_id == payload.room_id,
            KeyAssignment.issued_at == payload.issued_at,
            KeyAssignment.returned_at.is_(None),
        )
    )
    if existing_open is not None:
        raise HTTPException(status_code=409, detail="Duplicate assignment detected. Please refresh before retrying.")

    row = KeyAssignment(**payload.model_dump())
    key.available_quantity -= 1
    db.add(row)
    return row


@router.post("/key-assignments/{assignment_id}/return", response_model=KeyAssignmentRead, dependencies=[Depends(verify_csrf)])
def return_key_assignment(
    assignment_id: int,
    payload: KeyAssignmentReturn,
    actor: User = Depends(require_role(Role.SUPER_ADMIN, Role.ADMIN, Role.EDITOR)),
    db: Session = Depends(get_db),
):
    row = db.scalar(select(KeyAssignment).where(KeyAssignment.id == assignment_id).with_for_update())
    if row is None:
        raise HTTPException(status_code=404, detail="Assignment not found.")
    if row.returned_at is not None:
        raise HTTPException(status_code=400, detail="Assignment is already returned.")

    key = db.scalar(select(Key).where(Key.id == row.key_id).with_for_update())
    if key is None:
        raise HTTPException(status_code=404, detail="Key not found.")
    if key.available_quantity >= key.total_quantity:
        raise HTTPException(status_code=400, detail="Key inventory is already fully returned.")

    before = _key_assignment_snapshot(row)
    row.returned_at = payload.returned_at
    row.return_note = payload.return_note
    key.available_quantity += 1
    audit(
        db,
        entity=row,
        action="returned",
        actor_user_id=actor.id,
        before=before,
        after=_key_assignment_snapshot(row),
    )
    db.commit()
    db.refresh(row)
    return row


@router.get("/equipment", response_model=list[EquipmentRead])
def list_equipment(
    _: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return list(db.scalars(select(Equipment).order_by(Equipment.name.asc())).all())


@router.post("/equipment", response_model=EquipmentRead, status_code=201, dependencies=[Depends(verify_csrf)])
def create_equipment(
    payload: EquipmentCreate,
    actor: User = Depends(require_role(Role.SUPER_ADMIN, Role.ADMIN, Role.EDITOR)),
    db: Session = Depends(get_db),
):
    row = Equipment(**payload.model_dump())
    db.add(row)
    try:
        db.flush()
        audit(db, entity=row, action="created", actor_user_id=actor.id, after=_equipment_snapshot(row))
        db.commit()
    except Exception as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail="Equipment already exists.") from exc
    db.refresh(row)
    return row


@router.patch("/equipment/{equipment_id}", response_model=EquipmentRead, dependencies=[Depends(verify_csrf)])
def update_equipment(
    equipment_id: int,
    payload: EquipmentUpdate,
    actor: User = Depends(require_role(Role.SUPER_ADMIN, Role.ADMIN, Role.EDITOR)),
    db: Session = Depends(get_db),
):
    row = db.get(Equipment, equipment_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Equipment not found.")
    before = _equipment_snapshot(row)
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(row, key, value)
    try:
        db.flush()
        audit(db, entity=row, action="updated", actor_user_id=actor.id, before=before,
              after=_equipment_snapshot(row))
        db.commit()
    except Exception as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail="Equipment name already in use.") from exc
    db.refresh(row)
    return row


@router.delete("/equipment/{equipment_id}", status_code=204, dependencies=[Depends(verify_csrf)])
def delete_equipment(
    equipment_id: int,
    actor: User = Depends(require_role(Role.SUPER_ADMIN, Role.ADMIN)),
    db: Session = Depends(get_db),
):
    row = db.get(Equipment, equipment_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Equipment not found.")

    # Refuse rather than cascade: a booking that asked for this equipment is a
    # record of what was agreed, and deleting the row would rewrite history.
    requested = db.scalar(
        select(func.count())
        .select_from(BookingEquipmentRequest)
        .where(BookingEquipmentRequest.equipment_id == equipment_id)
    )
    if requested:
        raise HTTPException(
            status_code=400,
            detail="This equipment has been requested on bookings and cannot be deleted.",
        )

    # Room links cascade (Equipment.room_links is delete-orphan), so without
    # this the delete would quietly empty every room the type stood in. Rooms
    # are set up one at a time; taking their kit away wholesale is not what
    # anyone means by deleting a catalogue entry.
    in_rooms = db.scalar(
        select(func.count()).select_from(RoomEquipment).where(RoomEquipment.equipment_id == equipment_id)
    )
    if in_rooms:
        raise HTTPException(
            status_code=400,
            detail=f"This equipment is in {in_rooms} room(s). Remove it from those rooms first.",
        )

    audit(db, entity=row, action="deleted", actor_user_id=actor.id, before=_equipment_snapshot(row))
    db.delete(row)
    db.commit()
    return None


@router.get("/room-equipment", response_model=list[RoomEquipmentRead])
def list_room_equipment(
    _: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return list(db.scalars(select(RoomEquipment).order_by(RoomEquipment.id.asc())).all())


@router.post("/room-equipment", response_model=RoomEquipmentRead, status_code=201, dependencies=[Depends(verify_csrf)])
def create_room_equipment(
    payload: RoomEquipmentCreate,
    actor: User = Depends(require_role(Role.SUPER_ADMIN, Role.ADMIN, Role.EDITOR)),
    db: Session = Depends(get_db),
):
    if db.get(Room, payload.room_id) is None:
        raise HTTPException(status_code=404, detail="Room not found.")
    if db.get(Equipment, payload.equipment_id) is None:
        raise HTTPException(status_code=404, detail="Equipment not found.")

    row = RoomEquipment(**payload.model_dump())
    db.add(row)
    try:
        db.flush()
        audit(db, entity="room_equipment", entity_id=row.id, action="created", actor_user_id=actor.id, after=_room_equipment_snapshot(row))
        db.commit()
    except Exception as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail="Room equipment already exists.") from exc
    db.refresh(row)
    return row


@router.patch(
    "/room-equipment/{link_id}", response_model=RoomEquipmentRead, dependencies=[Depends(verify_csrf)]
)
def update_room_equipment(
    link_id: int,
    payload: RoomEquipmentUpdate,
    actor: User = Depends(require_role(Role.SUPER_ADMIN, Role.ADMIN, Role.EDITOR)),
    db: Session = Depends(get_db),
):
    row = db.get(RoomEquipment, link_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Room equipment not found.")
    before = _room_equipment_snapshot(row)
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(row, key, value)
    if row.quantity < 0:
        raise HTTPException(status_code=400, detail="Quantity cannot be negative.")
    db.flush()
    audit(db, entity="room_equipment", entity_id=row.id, action="updated", actor_user_id=actor.id,
          before=before, after=_room_equipment_snapshot(row))
    db.commit()
    db.refresh(row)
    return row


@router.delete("/room-equipment/{link_id}", status_code=204, dependencies=[Depends(verify_csrf)])
def delete_room_equipment(
    link_id: int,
    actor: User = Depends(require_role(Role.SUPER_ADMIN, Role.ADMIN, Role.EDITOR)),
    db: Session = Depends(get_db),
):
    """Unlink equipment from a room.

    Safe to allow even where bookings requested it: the booking keeps its own
    line item, which records what was asked for at the time.
    """
    row = db.get(RoomEquipment, link_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Room equipment not found.")
    audit(db, entity="room_equipment", entity_id=row.id, action="deleted", actor_user_id=actor.id,
          before=_room_equipment_snapshot(row))
    db.delete(row)
    db.commit()
    return None


@router.get("/internet-connections", response_model=list[InternetConnectionRead])
def list_internet_connections(
    _: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return list(db.scalars(select(InternetConnection).order_by(InternetConnection.id.asc())).all())


@router.post("/internet-connections", response_model=InternetConnectionRead, status_code=201, dependencies=[Depends(verify_csrf)])
def create_internet_connection(
    payload: InternetConnectionCreate,
    actor: User = Depends(require_role(Role.SUPER_ADMIN, Role.ADMIN, Role.EDITOR)),
    db: Session = Depends(get_db),
):
    if db.get(Room, payload.room_id) is None:
        raise HTTPException(status_code=404, detail="Room not found.")
    row = InternetConnection(**payload.model_dump())
    db.add(row)
    db.flush()
    audit(db, entity="internet_connection", entity_id=row.id, action="created", actor_user_id=actor.id, after=_internet_connection_snapshot(row))
    db.commit()
    db.refresh(row)
    return row
