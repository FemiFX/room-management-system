"""Admin CRUD for the booking services catalogue.

The reference app hardcoded ["Technician", "Usher"] in two places in its
source, so changing the list meant a deploy. This makes it data, and gives
staff somewhere to manage it.
"""

from __future__ import annotations

import re

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_role, verify_csrf
from app.db.session import get_db
from app.models.booking_request import BookingServiceRequest
from app.models.booking_service import BookingService
from app.models.enums import Role
from app.models.room import Room
from app.models.room_service import RoomService
from app.models.user import User
from app.schemas.common import ORMModel
from app.services.audit import audit

router = APIRouter(tags=["booking-services"])

_WRITE_ROLES = (Role.SUPER_ADMIN, Role.ADMIN, Role.EDITOR)


class BookingServiceCreate(BaseModel):
    #: Optional: when a service is created inline (from the room panel's add
    #: field) there is nothing to type a machine key into, so the server
    #: derives one from the name. Still accepted when a caller has its own.
    code: str | None = Field(default=None, max_length=50)
    name: str = Field(min_length=1, max_length=150)
    description: str | None = None
    is_active: bool = True
    sort_order: int = 0


class BookingServiceUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    is_active: bool | None = None
    sort_order: int | None = None


class BookingServiceRead(ORMModel):
    id: int
    code: str
    name: str
    description: str | None
    is_active: bool
    sort_order: int


def _derived_code(db: Session, name: str) -> str:
    """A stable machine key derived from a display name.

    Only used when the caller supplied no code -- the inline "create and add"
    field has nowhere to type one. A counter keeps that gesture to one step.

    An EXPLICIT code is never rewritten this way: asking for a code that is
    taken is a conflict the caller needs to hear about, not something to
    quietly rename.
    """
    slug = re.sub(r"[^a-z0-9]+", "-", name.strip().lower()).strip("-")[:50] or "service"
    candidate = slug
    suffix = 2
    while db.scalar(select(BookingService).where(BookingService.code == candidate)) is not None:
        tail = f"-{suffix}"
        candidate = slug[: 50 - len(tail)] + tail
        suffix += 1
    return candidate


def _snapshot(row: BookingService) -> dict:
    return {
        "code": row.code,
        "name": row.name,
        "description": row.description,
        "is_active": row.is_active,
        "sort_order": row.sort_order,
    }


@router.get("/booking-services", response_model=list[BookingServiceRead])
def list_services(_: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return list(
        db.scalars(
            select(BookingService).order_by(
                BookingService.sort_order.asc(), BookingService.name.asc()
            )
        ).all()
    )


@router.post(
    "/booking-services", response_model=BookingServiceRead, status_code=201,
    dependencies=[Depends(verify_csrf)],
)
def create_service(
    payload: BookingServiceCreate,
    actor: User = Depends(require_role(*_WRITE_ROLES)),
    db: Session = Depends(get_db),
):
    data = payload.model_dump()
    supplied = (data.get("code") or "").strip().lower()
    data["code"] = supplied or _derived_code(db, data["name"])
    row = BookingService(**data)
    db.add(row)
    try:
        db.flush()
        audit(db, entity=row, action="created", actor_user_id=actor.id, after=_snapshot(row))
        db.commit()
    except Exception as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail="That service code already exists.") from exc
    db.refresh(row)
    return row


@router.patch(
    "/booking-services/{service_id}", response_model=BookingServiceRead,
    dependencies=[Depends(verify_csrf)],
)
def update_service(
    service_id: int,
    payload: BookingServiceUpdate,
    actor: User = Depends(require_role(*_WRITE_ROLES)),
    db: Session = Depends(get_db),
):
    row = db.get(BookingService, service_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Service not found.")
    before = _snapshot(row)
    # `code` is deliberately not updatable: it is the stable machine key, and
    # bookings already reference this row.
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(row, key, value)
    db.flush()
    audit(db, entity=row, action="updated", actor_user_id=actor.id, before=before, after=_snapshot(row))
    db.commit()
    db.refresh(row)
    return row


@router.delete("/booking-services/{service_id}", status_code=204, dependencies=[Depends(verify_csrf)])
def delete_service(
    service_id: int,
    actor: User = Depends(require_role(Role.SUPER_ADMIN, Role.ADMIN)),
    db: Session = Depends(get_db),
):
    """Only ever removes a service nothing has requested.

    A service that appears on a booking is part of what was agreed. Deactivate
    it instead -- that takes it off the form while leaving the record intact.
    """
    row = db.get(BookingService, service_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Service not found.")

    requested = db.scalar(
        select(func.count())
        .select_from(BookingServiceRequest)
        .where(BookingServiceRequest.service_id == service_id)
    )
    if requested:
        raise HTTPException(
            status_code=400,
            detail="This service has been requested on bookings. Deactivate it instead.",
        )

    audit(db, entity=row, action="deleted", actor_user_id=actor.id, before=_snapshot(row))
    db.delete(row)
    db.commit()
    return None


# ---------------------------------------------------------------------------
# Per-room offering
# ---------------------------------------------------------------------------
#
# A row in `room_services` means "this room offers this service". Equipment has
# had the same shape all along; services were global until 20260903_0017.


class RoomServiceCreate(BaseModel):
    room_id: int
    service_id: int


class RoomServiceRead(ORMModel):
    id: int
    room_id: int
    service_id: int


@router.post("/room-services", response_model=RoomServiceRead, status_code=201, dependencies=[Depends(verify_csrf)])
def offer_service_in_room(
    payload: RoomServiceCreate,
    actor: User = Depends(require_role(*_WRITE_ROLES)),
    db: Session = Depends(get_db),
):
    if db.get(Room, payload.room_id) is None:
        raise HTTPException(status_code=404, detail="Room not found.")
    if db.get(BookingService, payload.service_id) is None:
        raise HTTPException(status_code=404, detail="Service not found.")

    row = RoomService(room_id=payload.room_id, service_id=payload.service_id)
    db.add(row)
    try:
        db.flush()
        audit(
            db, entity="room_services", entity_id=row.id, action="created", actor_user_id=actor.id,
            after={"room_id": row.room_id, "service_id": row.service_id},
        )
        db.commit()
    except Exception as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail="This room already offers that service.") from exc
    db.refresh(row)
    return row


@router.delete("/room-services/{link_id}", status_code=204, dependencies=[Depends(verify_csrf)])
def withdraw_service_from_room(
    link_id: int,
    actor: User = Depends(require_role(*_WRITE_ROLES)),
    db: Session = Depends(get_db),
):
    """Stops offering a service in one room.

    Bookings that already requested it keep their line -- this only changes
    what the public form offers from now on, exactly like deactivating a
    service does globally.
    """
    row = db.get(RoomService, link_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Not offered in that room.")
    audit(
        db, entity="room_services", entity_id=row.id, action="deleted", actor_user_id=actor.id,
        before={"room_id": row.room_id, "service_id": row.service_id},
    )
    db.delete(row)
    db.commit()
    return None
