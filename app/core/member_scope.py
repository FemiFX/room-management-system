"""Default-deny path containment for the MEMBER role.

Every API GET in this app authenticates with a bare ``get_current_user`` and
every HTML view only checks that *someone* is signed in, so authorisation for
reads is effectively "any active user sees everything". That is fine while all
roles are staff. It stops being fine the moment ``Role.MEMBER`` exists: a
synced account holder would otherwise read every building, party, lease,
key and document in the organisation.

Rather than audit ~40 route handlers and hope nobody adds a 41st, this
middleware inverts the default for members only: a member may reach the paths
on the allowlist below and nothing else. A route added years from now is
denied to members with no action by its author.

Non-member roles pass through untouched -- this middleware changes no existing
behaviour.
"""

from __future__ import annotations

import anyio
from starlette.responses import JSONResponse, RedirectResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from app.models.enums import Role

#: Paths a member may reach, matched exactly.
MEMBER_ALLOWED_EXACT = frozenset(
    {
        "/",
        "/health/live",
        "/health/ready",
        "/api/v1/auth/me",
        "/api/v1/set-language",
        "/api/v1/preferences",
        # Bare landing paths. These are exact, NOT prefixes: "/book" as a
        # prefix would also match "/bookings", the staff admin page.
        "/portal",
        "/book",
    }
)

#: Paths a member may reach, matched by prefix.
#:
#: Every entry MUST be more specific than "/" -- a bare "/" here would allow
#: the entire application and silently undo this whole module. That is the one
#: catastrophic edit available in this file, which is why the exact matches
#: above are kept in a separate constant.
#: Every prefix ends in "/" so it cannot swallow a sibling path that merely
#: shares an opening substring -- "/book" would match "/bookings".
MEMBER_ALLOWED_PREFIXES = (
    "/portal/",
    "/api/v1/portal/",
    "/book/",
    "/api/v1/public/",
    "/auth/",
    "/static/",
)


def member_may_access(path: str) -> bool:
    if path in MEMBER_ALLOWED_EXACT:
        return True
    return any(path.startswith(prefix) for prefix in MEMBER_ALLOWED_PREFIXES)


def _load_role(user_id: int) -> tuple[str | None, bool]:
    """Return ``(role, is_active)`` for a user id, or ``(None, False)``.

    Read fresh on every request rather than cached in the session cookie, so a
    demotion or deactivation takes effect on the next request instead of
    whenever the cookie happens to be reissued.
    """
    from sqlalchemy import select

    from app.db.session import get_session_factory
    from app.models.user import User

    with get_session_factory()() as db:
        row = db.execute(select(User.role, User.is_active).where(User.id == user_id)).first()
    if row is None:
        return None, False
    role, is_active = row
    return (role.value if isinstance(role, Role) else role), bool(is_active)


class MemberScopeMiddleware:
    """Confine ``Role.MEMBER`` sessions to the member-facing surface.

    Must be mounted *inside* SessionMiddleware so ``scope["session"]`` is
    populated. Starlette builds its middleware stack in reverse registration
    order, so in ``create_app`` this must be added **before** SessionMiddleware.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        session = scope.get("session")
        if session is None:
            # Only reachable if this middleware was mounted outside
            # SessionMiddleware. Fail closed and loudly rather than silently
            # letting every member through.
            response = JSONResponse(
                {"detail": "Server misconfiguration: session unavailable."},
                status_code=500,
            )
            await response(scope, receive, send)
            return

        user_id = session.get("user_id")
        if not user_id:
            await self.app(scope, receive, send)
            return

        role, is_active = await anyio.to_thread.run_sync(_load_role, user_id)
        if role != Role.MEMBER.value or not is_active:
            # Staff, and stale/inactive sessions, follow the normal auth path.
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")
        if member_may_access(path):
            await self.app(scope, receive, send)
            return

        if path.startswith("/api/"):
            response = JSONResponse({"detail": "Insufficient permissions."}, status_code=403)
        else:
            response = RedirectResponse(url="/portal", status_code=303)
        await response(scope, receive, send)
