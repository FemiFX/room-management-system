from __future__ import annotations

from pydantic import BaseModel
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, verify_csrf
from app.db.session import get_db
from app.models.user import User
from app.schemas.user import UserRead
from app.services.users import update_user

router = APIRouter(prefix="/preferences", tags=["preferences"])


class PreferenceUpdate(BaseModel):
    preferred_language: str


@router.patch("", response_model=UserRead, dependencies=[Depends(verify_csrf)])
def update_preferences(
    payload: PreferenceUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        return update_user(
            db,
            user=current_user,
            display_name=None,
            role=None,
            preferred_language=payload.preferred_language,
            is_active=None,
            actor_user_id=current_user.id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
