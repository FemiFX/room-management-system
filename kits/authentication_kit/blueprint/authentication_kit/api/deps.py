from __future__ import annotations

from collections.abc import Callable

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from authentication_kit.db.session import get_db
from authentication_kit.models.enums import Role
from authentication_kit.models.user import User


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


async def verify_csrf(request: Request) -> None:
    if request.method in {"POST", "PATCH", "DELETE"}:
        expected = request.session.get("csrf_token")
        actual = request.headers.get("x-csrf-token")
        if request.headers.get("content-type", "").startswith("application/x-www-form-urlencoded") or request.headers.get(
            "content-type", ""
        ).startswith("multipart/form-data"):
            form = await request.form()
            actual = actual or form.get("csrf_token")
        if not expected or expected != actual:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid CSRF token.")

