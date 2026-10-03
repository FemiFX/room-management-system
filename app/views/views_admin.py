from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.templating import templates
from app.db.session import get_db
from app.models.enums import Role
from app.models.user import User
from app.views.deps import base_admin_context, get_authenticated_user

router = APIRouter()

_ADMIN_ROLES = {Role.SUPER_ADMIN, Role.ADMIN}


@router.get("/admin/users", response_class=HTMLResponse)
def users_list(request: Request, db: Session = Depends(get_db)):
    user = get_authenticated_user(request, db)
    if not user:
        return RedirectResponse(url="/auth/login", status_code=303)
    if user.role not in _ADMIN_ROLES:
        return RedirectResponse(url="/dashboard", status_code=303)

    users = db.scalars(select(User).order_by(User.display_name)).all()

    ctx = base_admin_context(
        request, user, db, active_path="/admin/users",
        users=list(users),
    )
    return templates.TemplateResponse(request, "admin/users/list.html", ctx)


@router.get("/admin/audit-logs", response_class=HTMLResponse)
def audit_logs_list(request: Request, db: Session = Depends(get_db)):
    user = get_authenticated_user(request, db)
    if not user:
        return RedirectResponse(url="/auth/login", status_code=303)
    if user.role not in _ADMIN_ROLES:
        return RedirectResponse(url="/dashboard", status_code=303)

    ctx = base_admin_context(request, user, db, active_path="/admin/audit-logs")
    return templates.TemplateResponse(request, "admin/audit_logs/list.html", ctx)
