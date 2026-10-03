from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.core.templating import templates
from app.db.session import get_db
from app.views.deps import base_admin_context, get_authenticated_user

router = APIRouter()


@router.get("/preferences", response_class=HTMLResponse)
def preferences_page(request: Request, db: Session = Depends(get_db)):
    user = get_authenticated_user(request, db)
    if not user:
        return RedirectResponse(url="/auth/login", status_code=303)

    ctx = base_admin_context(
        request,
        user,
        db,
        active_path="/preferences",
    )
    return templates.TemplateResponse(request, "admin/preferences.html", ctx)
