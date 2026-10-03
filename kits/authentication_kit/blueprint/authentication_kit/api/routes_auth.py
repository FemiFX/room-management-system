from __future__ import annotations

from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from authentication_kit.api.deps import get_current_user, verify_csrf
from authentication_kit.auth.oidc import authorize_redirect, fetch_userinfo
from authentication_kit.core.config import get_settings
from authentication_kit.core.security import generate_csrf_token
from authentication_kit.core.templating import templates
from authentication_kit.db.session import get_db
from authentication_kit.models.enums import Role
from authentication_kit.models.user import User
from authentication_kit.schemas.user import UserRead
from authentication_kit.services.users import provision_dev_user, provision_oidc_user

router = APIRouter()


def template_context(request: Request, **kwargs: object) -> dict[str, object]:
    context: dict[str, object] = {"request": request, **kwargs}
    context["csrf_token"] = request.session.setdefault("csrf_token", generate_csrf_token())
    return context


def dev_auth_allowed() -> bool:
    settings = get_settings()
    return settings.dev_auth_enabled and settings.env != "production"


@router.get("/auth/login", name="auth_login", response_class=HTMLResponse)
async def auth_login_page(request: Request):
    settings = get_settings()
    if settings.oidc_enabled and not dev_auth_allowed():
        return await authorize_redirect(request)
    return templates.TemplateResponse(
        "auth/login.html",
        template_context(
            request,
            current_user=None,
            oidc_enabled=settings.oidc_enabled,
            dev_auth_enabled=dev_auth_allowed(),
            roles=[role.value for role in Role],
        ),
    )


@router.get("/auth/oidc")
async def auth_oidc(request: Request):
    return await authorize_redirect(request)


@router.get("/auth/callback", name="auth_callback")
async def auth_callback(request: Request, db: Session = Depends(get_db)):
    oidc_data = await fetch_userinfo(request)
    userinfo = oidc_data["userinfo"]
    oidc_subject = userinfo.get("sub")
    if not oidc_subject:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="OIDC response missing subject.")

    display_name = userinfo.get("name") or userinfo.get("preferred_username") or oidc_subject
    user = provision_oidc_user(
        db,
        oidc_subject=oidc_subject,
        display_name=display_name,
        email=userinfo.get("email"),
        oidc_issuer=userinfo.get("iss"),
    )
    request.session["user_id"] = user.id
    request.session.setdefault("csrf_token", generate_csrf_token())
    return RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/auth/logout", dependencies=[Depends(verify_csrf)])
def auth_logout(request: Request):
    request.session.clear()
    return RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/auth/dev-login", dependencies=[Depends(verify_csrf)])
def auth_dev_login(
    request: Request,
    email: str | None = Form(default=None),
    display_name: str = Form(...),
    role: Role = Form(default=Role.SUPER_ADMIN),
    db: Session = Depends(get_db),
):
    if not dev_auth_allowed():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)

    user = provision_dev_user(
        db,
        email=email.strip() or None if email else None,
        display_name=display_name.strip(),
        role=role,
    )
    request.session["user_id"] = user.id
    request.session.setdefault("csrf_token", generate_csrf_token())
    return RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/api/me", response_model=UserRead)
def me(current_user: User = Depends(get_current_user)) -> User:
    return current_user
