from __future__ import annotations

from app.models.enums import NotificationStatus
from app.models.notification import Notification
from app.models.user import User


def test_delete_all_read_notifications(client, dev_login, db_session):
    csrf = dev_login(role="admin", email="notifications-admin@example.com")
    user = db_session.query(User).filter(User.email == "notifications-admin@example.com").one()

    db_session.add_all(
        [
            Notification(
                user_id=user.id,
                title="Read 1",
                message="m1",
                status=NotificationStatus.READ,
            ),
            Notification(
                user_id=user.id,
                title="Read 2",
                message="m2",
                status=NotificationStatus.READ,
            ),
            Notification(
                user_id=user.id,
                title="Unread",
                message="m3",
                status=NotificationStatus.UNREAD,
            ),
        ]
    )
    db_session.commit()

    response = client.delete("/api/v1/notifications/delete-all-read", headers={"x-csrf-token": csrf})
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["deleted"] == 2

    remaining = db_session.query(Notification).filter(Notification.user_id == user.id).all()
    assert len(remaining) == 1
    assert remaining[0].status == NotificationStatus.UNREAD
