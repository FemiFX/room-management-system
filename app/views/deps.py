from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.i18n import get_supported_languages, gettext, language_display_name, resolve_language
from app.core.security import generate_csrf_token
from app.models.enums import NotificationStatus, Role
from app.models.notification import Notification
from app.models.user import User


def get_authenticated_user(request, db: Session) -> User | None:
    """Return User if authenticated, else None."""
    user_id = request.session.get("user_id")
    if not user_id:
        return None
    user = db.get(User, user_id)
    return user if user and user.is_active else None


_ADMIN_ROLES_SET = {"super_admin", "admin"}


def build_nav_sections(
    active_path: str, *, request, user: User, open_requests: int = 0
) -> list[dict]:
    """Build the nav_sections list consumed by sidebar partials."""
    _ = lambda message: gettext(message, request=request, user=user)

    def active(url: str, exact: bool = False) -> bool:
        if exact:
            return active_path == url
        return active_path.startswith(url)

    is_admin = user.role.value in _ADMIN_ROLES_SET

    sections: list[dict] = [
        {"is_header": True, "label": _("OVERVIEW")},
        {
            "is_header": False, "single": True,
            "id": "dashboard", "label": _("Dashboard"), "icon": "gauge",
            "url": "/dashboard", "active": active("/dashboard", exact=True),
        },
        {
            "is_header": False, "single": True,
            "id": "action-center", "label": _("Action Center"), "icon": "bolt",
            "url": "/action-center", "active": active("/action-center", exact=True),
        },
        {"is_header": True, "label": _("SPACES")},
        {
            "is_header": False, "single": True,
            "id": "buildings", "label": _("Buildings"), "icon": "building",
            "url": "/buildings", "active": active("/buildings"),
        },
        {
            "is_header": False, "single": True,
            "id": "rooms", "label": _("Rooms"), "icon": "door",
            "url": "/rooms", "active": active("/rooms"),
        },
        {"is_header": True, "label": _("OCCUPANCY")},
        {
            "is_header": False, "single": False,
            "id": "occupancy", "label": _("Occupancy"), "icon": "users",
            "active": active("/parties") or active("/leases"),
            "open": active("/parties") or active("/leases"),
            "children": [
                {"label": _("Parties"), "url": "/parties", "active": active("/parties")},
                {"label": _("Leases"), "url": "/leases", "active": active("/leases")},
            ],
        },
        {"is_header": True, "label": _("BOOKINGS")},
        # Flat, not a collapsible group. "All Bookings" and "Calendar" are now
        # two views of one page, which left a group of one real destination
        # plus setup -- a disclosure triangle hiding nothing worth hiding.
        # Two workflows, two entries. A request waiting for a decision and a
        # booking that already has one are different jobs with different
        # columns and different actions; the count says how many are waiting
        # without anyone having to open the page.
        {
            # One entry: a request and a booking are the same row in different
            # states, and the list shows the waiting ones first. The number
            # says how many that is without anyone opening the page.
            "is_header": False, "single": True,
            "id": "bookings", "label": _("Bookings"), "icon": "calendar",
            "url": "/bookings",
            "badge": open_requests or None,
            "active": (
                active("/bookings")
                and not active("/bookings/setup")
                and not active("/bookings/catalogue")
            ),
        },
        {
            # Two pages, one entry: the room view and the catalogue are the
            # same job seen from either end, and they link to each other.
            "is_header": False, "single": True,
            "id": "bookings-setup", "label": _("Equipment & Services"), "icon": "sliders",
            "url": "/bookings/setup",
            "active": active("/bookings/setup") or active("/bookings/catalogue"),
        },
        # The two customer-facing surfaces. Staff had no way into either one:
        # the public site was reachable only by typing its URL, and the portal
        # was linked from nothing but its own layout. Both open in a new tab
        # because they are a different shell, not another admin page.
        #
        # "/book" is matched EXACTLY. As a prefix it also matches "/bookings",
        # which would leave this item lit on every staff booking page --
        # the same trap MEMBER_ALLOWED_EXACT documents in core/member_scope.py.
        {
            "is_header": False, "single": True,
            "id": "public-booking", "label": _("Public Booking Site"), "icon": "globe",
            "url": "/book", "target": "_blank", "active": active("/book", exact=True),
        },
        {
            "is_header": False, "single": True,
            "id": "member-portal", "label": _("Member Portal"), "icon": "person",
            "url": "/portal", "target": "_blank", "active": active("/portal", exact=True),
        },
        {"is_header": True, "label": _("ACCESS & INFRASTRUCTURE")},
        {
            "is_header": False, "single": True,
            "id": "keys", "label": _("Keys"), "icon": "key",
            "url": "/keys", "active": active("/keys"),
        },
        {
            "is_header": False, "single": True,
            "id": "infrastructure", "label": _("Infrastructure"), "icon": "wifi",
            "url": "/infrastructure", "active": active("/infrastructure"),
        },
        {"is_header": True, "label": _("DOCUMENTS")},
        {
            "is_header": False, "single": True,
            "id": "documents", "label": _("Documents"), "icon": "file-contract",
            "url": "/documents", "active": active("/documents"),
        },
        {"is_header": True, "label": _("NOTIFICATIONS")},
        {
            "is_header": False, "single": True,
            "id": "notifications", "label": _("Notifications"), "icon": "bell",
            "url": "/notifications", "active": active("/notifications"),
        },
        {"is_header": True, "label": _("ADMINISTRATION")},
        {
            "is_header": False, "single": True,
            "id": "integrations", "label": _("Integrations"), "icon": "settings",
            "url": "/integrations", "active": active("/integrations"),
        },
        {
            "is_header": False, "single": True,
            "id": "preferences", "label": _("Preferences"), "icon": "settings",
            "url": "/preferences", "active": active("/preferences"),
        },
        {
            "is_header": False, "single": True,
            "id": "users", "label": _("Users & Roles"), "icon": "users",
            "url": "/admin/users", "active": active("/admin/users"),
        },
    ]

    if is_admin:
        sections.append({
            "is_header": False, "single": True,
            "id": "audit-logs", "label": _("Audit Log"), "icon": "shield-halved",
            "url": "/admin/audit-logs", "active": active("/admin/audit-logs"),
        })

    return sections


def open_requests(db: Session) -> int:
    """How many bookings are waiting for a decision.

    In the sidebar next to "Anfragen", so a queue that is filling up is
    visible from any page rather than only to whoever opens it.
    """
    from app.models.booking import Booking
    from app.models.enums import BookingStatus

    return db.scalar(
        select(func.count()).select_from(Booking).where(Booking.status == BookingStatus.PENDING)
    ) or 0


def build_notifications_context(db: Session, user: User) -> dict:
    """Fetch 12 most recent notifications and unread count for header."""
    stmt = (
        select(Notification)
        .where(Notification.user_id == user.id)
        .order_by(Notification.created_at.desc())
        .limit(12)
    )
    notifications = list(db.scalars(stmt).all())
    unread_count = db.scalar(
        select(func.count(Notification.id)).where(
            Notification.user_id == user.id,
            Notification.status == NotificationStatus.UNREAD,
        )
    ) or 0
    return {"notifications": notifications, "unread_count": unread_count}


def base_admin_context(request, user: User, db: Session, active_path: str, **kwargs) -> dict:
    """Assemble the full context dict required by admin/layout.html."""
    # Every admin HTML view funnels through here, so this is the one place that
    # can catch a member reaching the admin shell. Raising rather than
    # redirecting is deliberate: MemberScopeMiddleware should already have
    # handled it, so arriving here means containment failed and that should be
    # loud rather than papered over.
    if user.role == Role.MEMBER:
        raise HTTPException(status_code=403, detail="Insufficient permissions.")

    csrf_token = request.session.setdefault("csrf_token", generate_csrf_token())
    notif_ctx = build_notifications_context(db, user)
    initials = "".join(p[0].upper() for p in user.display_name.split()[:2]) or "U"
    current_language = resolve_language(request, user=user)
    language_options = [{"code": code, "label": language_display_name(code)} for code in get_supported_languages()]
    return {
        "request": request,
        "csrf_token": csrf_token,
        "current_user": user,
        "current_language": current_language,
        "supported_languages": get_supported_languages(),
        "language_options": language_options,
        "user_name": user.display_name,
        "user_email": user.email,
        "user_role": user.role.value,
        "user_initials": initials,
        "nav_sections": build_nav_sections(
            active_path, request=request, user=user, open_requests=open_requests(db)
        ),
        **notif_ctx,
        **kwargs,
    }
