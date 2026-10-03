from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.user import User
from app.schemas.domain import ActionCenterItem, DashboardRead
from app.services.dashboard import action_center_items, dashboard_summary

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("/summary", response_model=DashboardRead)
def get_dashboard_summary(
    _: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return DashboardRead(**dashboard_summary(db))


@router.get("/action-center", response_model=list[ActionCenterItem])
def get_action_center(
    _: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return [ActionCenterItem(**item) for item in action_center_items(db)]
