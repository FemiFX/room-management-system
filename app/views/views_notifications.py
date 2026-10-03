from __future__ import annotations

import math

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.templating import templates
from app.db.session import get_db
from app.models.enums import NotificationStatus
from app.models.notification import Notification
from app.views.deps import base_admin_context, get_authenticated_user

router = APIRouter()

PAGE_SIZE = 20


@router.get("/notifications", response_class=HTMLResponse)
def notifications_page(request: Request, db: Session = Depends(get_db)):
    user = get_authenticated_user(request, db)
    if not user:
        return RedirectResponse(url="/auth/login", status_code=303)

    status_filter = request.query_params.get("status", "all")
    page = max(1, int(request.query_params.get("page", "1")))

    stmt = select(Notification).where(Notification.user_id == user.id)
    if status_filter == "unread":
        stmt = stmt.where(Notification.status == NotificationStatus.UNREAD)
    elif status_filter == "read":
        stmt = stmt.where(Notification.status == NotificationStatus.READ)

    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    total_pages = max(1, math.ceil(total / PAGE_SIZE))
    page = min(page, total_pages)

    notifications = list(
        db.scalars(
            stmt.order_by(Notification.created_at.desc())
            .offset((page - 1) * PAGE_SIZE)
            .limit(PAGE_SIZE)
        ).all()
    )

    unread_total = db.scalar(
        select(func.count(Notification.id)).where(
            Notification.user_id == user.id,
            Notification.status == NotificationStatus.UNREAD,
        )
    ) or 0

    ctx = base_admin_context(
        request, user, db, active_path="/notifications",
        page_notifications=notifications,
        status_filter=status_filter,
        current_page=page,
        total_pages=total_pages,
        total=total,
        unread_total=unread_total,
    )
    return templates.TemplateResponse(request, "admin/notifications.html", ctx)
