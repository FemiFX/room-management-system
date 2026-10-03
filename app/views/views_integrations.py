from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.enums import Role
from app.views.deps import base_admin_context, get_authenticated_user

router = APIRouter()

_ADMIN_ROLES = {Role.SUPER_ADMIN, Role.ADMIN}


@router.get("/integrations", response_class=HTMLResponse)
def integrations_page(request: Request, db: Session = Depends(get_db)):
    user = get_authenticated_user(request, db)
    if not user:
        return RedirectResponse(url="/auth/login", status_code=303)
    if user.role not in _ADMIN_ROLES:
        return RedirectResponse(url="/dashboard", status_code=303)

    from app.core.templating import templates

    ctx = base_admin_context(
        request,
        user,
        db,
        active_path="/integrations",
    )
    return templates.TemplateResponse(request, "admin/integrations/list.html", ctx)

