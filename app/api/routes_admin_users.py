from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import require_role, verify_csrf
from app.db.session import get_db
from app.models.enums import Role
from app.models.user import User
from app.schemas.user import UserCreate, UserRead, UserUpdate
from app.services.users import activate_user, create_user, update_user

router = APIRouter(prefix="/admin/users", tags=["admin-users"])


@router.get("", response_model=list[UserRead])
def list_users(
    _: User = Depends(require_role(Role.SUPER_ADMIN, Role.ADMIN)),
    db: Session = Depends(get_db),
):
    return list(db.scalars(select(User).order_by(User.id.asc())).all())


@router.post("", response_model=UserRead, status_code=201, dependencies=[Depends(verify_csrf)])
def create_user_endpoint(
    payload: UserCreate,
    actor: User = Depends(require_role(Role.SUPER_ADMIN, Role.ADMIN)),
    db: Session = Depends(get_db),
):
    try:
        return create_user(
            db,
            email=payload.email,
            display_name=payload.display_name,
            role=payload.role,
            preferred_language=payload.preferred_language,
            is_active=payload.is_active,
            actor_user_id=actor.id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.patch("/{user_id}", response_model=UserRead, dependencies=[Depends(verify_csrf)])
def patch_user_endpoint(
    user_id: int,
    payload: UserUpdate,
    actor: User = Depends(require_role(Role.SUPER_ADMIN, Role.ADMIN)),
    db: Session = Depends(get_db),
):
    target = db.get(User, user_id)
    if target is None:
        raise HTTPException(status_code=404, detail="User not found.")
    try:
        return update_user(
            db,
            user=target,
            display_name=payload.display_name,
            role=payload.role,
            preferred_language=payload.preferred_language,
            is_active=payload.is_active,
            actor_user_id=actor.id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/{user_id}/activate", response_model=UserRead, dependencies=[Depends(verify_csrf)])
def activate_user_endpoint(
    user_id: int,
    actor: User = Depends(require_role(Role.SUPER_ADMIN, Role.ADMIN)),
    db: Session = Depends(get_db),
):
    target = db.get(User, user_id)
    if target is None:
        raise HTTPException(status_code=404, detail="User not found.")
    return activate_user(db, user=target, actor_user_id=actor.id, is_active=True)


@router.post("/{user_id}/deactivate", response_model=UserRead, dependencies=[Depends(verify_csrf)])
def deactivate_user_endpoint(
    user_id: int,
    actor: User = Depends(require_role(Role.SUPER_ADMIN, Role.ADMIN)),
    db: Session = Depends(get_db),
):
    target = db.get(User, user_id)
    if target is None:
        raise HTTPException(status_code=404, detail="User not found.")
    return activate_user(db, user=target, actor_user_id=actor.id, is_active=False)
