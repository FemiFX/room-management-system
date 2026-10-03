from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.core.templating import templates
from app.db.session import get_db
from app.models.enums import Role
from app.models.user import User
from app.services.dashboard import action_center_items, dashboard_summary
from app.views.deps import base_admin_context, get_authenticated_user

router = APIRouter()


@router.get("/", response_class=RedirectResponse)
def index(request: Request, db: Session = Depends(get_db)):
    """Send each audience to its own home. /auth/callback redirects here."""
    user = get_authenticated_user(request, db)
    if user and user.role == Role.MEMBER:
        return RedirectResponse(url="/portal", status_code=303)
    return RedirectResponse(url="/dashboard", status_code=303)


@router.get("/dashboard", response_class=HTMLResponse)
def dashboard_page(request: Request, db: Session = Depends(get_db)):
    user = get_authenticated_user(request, db)
    if not user:
        return RedirectResponse(url="/auth/login", status_code=303)

    summary = dashboard_summary(db)
    ctx = base_admin_context(
        request, user, db,
        active_path="/dashboard",
        summary=summary,
    )
    return templates.TemplateResponse(request, "admin/dashboard.html", ctx)


@router.get("/action-center", response_class=HTMLResponse)
def action_center_page(request: Request, db: Session = Depends(get_db)):
    user = get_authenticated_user(request, db)
    if not user:
        return RedirectResponse(url="/auth/login", status_code=303)

    actions = action_center_items(db)

    ctx = base_admin_context(
        request, user, db,
        active_path="/action-center",
        action_items=actions,
    )
    return templates.TemplateResponse(request, "admin/action_center.html", ctx)
