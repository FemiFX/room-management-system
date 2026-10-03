from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, verify_csrf
from app.db.session import get_db
from app.models.enums import NotificationStatus
from app.models.notification import Notification
from app.models.user import User
from app.schemas.domain import NotificationRead
from app.services.notifications import mark_notification_status

router = APIRouter(prefix="/notifications", tags=["notifications"])


@router.get("", response_model=list[NotificationRead])
def list_notifications(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    stmt = select(Notification).where(Notification.user_id == current_user.id).order_by(Notification.created_at.desc())
    return list(db.scalars(stmt).all())


@router.get("/unread-count")
def unread_count(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    count = len(
        db.scalars(
            select(Notification.id).where(
                Notification.user_id == current_user.id,
                Notification.status == NotificationStatus.UNREAD,
            )
        ).all()
    )
    return {"unread_count": count}


@router.post("/{notification_id}/mark-read", response_model=NotificationRead, dependencies=[Depends(verify_csrf)])
def mark_read(
    notification_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    notification = db.get(Notification, notification_id)
    if notification is None or notification.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Notification not found.")
    return mark_notification_status(db, notification=notification, status=NotificationStatus.READ)


@router.post("/{notification_id}/mark-unread", response_model=NotificationRead, dependencies=[Depends(verify_csrf)])
def mark_unread(
    notification_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    notification = db.get(Notification, notification_id)
    if notification is None or notification.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Notification not found.")
    return mark_notification_status(db, notification=notification, status=NotificationStatus.UNREAD)


@router.post("/mark-all-read", dependencies=[Depends(verify_csrf)])
def mark_all_read(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    rows = db.scalars(
        select(Notification).where(
            Notification.user_id == current_user.id,
            Notification.status == NotificationStatus.UNREAD,
        )
    ).all()
    now = datetime.now(timezone.utc)
    for row in rows:
        row.status = NotificationStatus.READ
        row.read_at = now
    db.commit()
    return {"status": "ok", "updated": len(rows)}


@router.delete("/delete-all-read", dependencies=[Depends(verify_csrf)])
def delete_all_read(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    stmt = delete(Notification).where(
        Notification.user_id == current_user.id,
        Notification.status == NotificationStatus.READ,
    )
    result = db.execute(stmt)
    db.commit()
    return {"status": "ok", "deleted": result.rowcount or 0}


@router.delete("/{notification_id}", status_code=204, dependencies=[Depends(verify_csrf)])
def delete_notification(
    notification_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    notification = db.get(Notification, notification_id)
    if notification is None or notification.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Notification not found.")
    db.delete(notification)
    db.commit()
