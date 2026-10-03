from __future__ import annotations

from collections.abc import Callable

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.enums import STAFF_ROLES, Role
from app.models.user import User


def get_current_user(request: Request, db: Session = Depends(get_db)) -> User:
    user_id = request.session.get("user_id")
    if not user_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required.")
    user = db.get(User, user_id)
    if user is None or not user.is_active:
        request.session.clear()
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required.")
    return user


def get_optional_user(request: Request, db: Session = Depends(get_db)) -> User | None:
    user_id = request.session.get("user_id")
    if not user_id:
        return None
    user = db.get(User, user_id)
    return user if user and user.is_active else None


def require_role(*roles: Role) -> Callable[[User], User]:
    def dependency(current_user: User = Depends(get_current_user)) -> User:
        if current_user.role not in roles:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions.")
        return current_user

    return dependency


def require_staff() -> Callable[[User], User]:
    """Any role except MEMBER.

    Attached to the admin API routers as a whole, so a new route added to one
    of them inherits the restriction instead of relying on its author to
    remember. MemberScopeMiddleware already blocks members by path; this is the
    second layer, and the one that survives a mistaken allowlist edit.
    """
    return require_role(*STAFF_ROLES)


def require_member() -> Callable[[User], User]:
    return require_role(Role.MEMBER)


def require_member_or_staff() -> Callable[[User], User]:
    """The member portal, which staff may also open to support a member."""
    return require_role(Role.MEMBER, *STAFF_ROLES)


async def verify_csrf(request: Request) -> None:
    if request.method in {"POST", "PATCH", "DELETE"}:
        expected = request.session.get("csrf_token")
        actual = request.headers.get("x-csrf-token")
        content_type = request.headers.get("content-type", "")
        if content_type.startswith("application/x-www-form-urlencoded") or content_type.startswith("multipart/form-data"):
            form = await request.form()
            actual = actual or form.get("csrf_token")
        if not expected or expected != actual:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid CSRF token.")
