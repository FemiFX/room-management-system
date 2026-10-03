from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.enums import NotificationStatus, Role
from app.models.notification import Notification
from app.models.user import User


def create_notification(
    db: Session,
    *,
    user_id: int,
    title: str,
    message: str,
    link: str | None = None,
    details_json: dict | None = None,
) -> Notification:
    notification = Notification(
        user_id=user_id,
        title=title,
        message=message,
        link=link,
        status=NotificationStatus.UNREAD,
        details_json=details_json,
    )
    db.add(notification)
    db.flush()
    return notification


def admin_user_ids(db: Session) -> list[int]:
    stmt = select(User.id).where(User.role.in_([Role.SUPER_ADMIN, Role.ADMIN]), User.is_active.is_(True))
    return [row for row in db.scalars(stmt)]


def fanout_admin_notification(
    db: Session,
    *,
    title: str,
    message: str,
    link: str | None = None,
    details_json: dict | None = None,
) -> int:
    user_ids = admin_user_ids(db)
    for user_id in user_ids:
        create_notification(
            db,
            user_id=user_id,
            title=title,
            message=message,
            link=link,
            details_json=details_json,
        )
    db.commit()
    return len(user_ids)


def mark_notification_status(db: Session, *, notification: Notification, status: NotificationStatus) -> Notification:
    notification.status = status
    notification.read_at = datetime.now(timezone.utc) if status == NotificationStatus.READ else None
    db.commit()
    db.refresh(notification)
    return notification
