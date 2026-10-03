from __future__ import annotations

from authlib.integrations.base_client.errors import OAuthError
from fastapi import APIRouter, Body, Depends, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, verify_csrf
from app.auth.oidc import authorize_redirect, fetch_userinfo
from app.core.config import get_settings
from app.core.i18n import get_supported_languages, gettext, resolve_language, set_request_language
from app.core.security import generate_csrf_token
from app.core.templating import templates
from app.db.session import get_db
from app.models.enums import Role
from app.models.user import User
from app.schemas.user import MeRead, UserRead
from app.services.users import OIDCLoginError, OIDCUserInfo, provision_dev_user, provision_oidc_preapproved_user

router = APIRouter()


_LOGIN_ERROR_MESSAGES: dict[str, str] = {
    "oidc_missing_subject": "The identity provider did not return a subject identifier.",
    "oidc_missing_email": "The identity provider did not return an email address.",
    "not_preapproved": "Your account is not pre-approved for single sign-on. Please contact an administrator.",
    "inactive": "Your account is inactive. Please contact an administrator.",
    "subject_mismatch": "This account is already bound to a different identity. Please contact an administrator.",
    "issuer_mismatch": "The identity provider does not match the one on file. Please contact an administrator.",
    "sso_failed": "Single sign-on could not be completed. Please try again or contact an administrator if the issue persists.",
}


def _login_error_message(request: Request, code: str | None) -> str | None:
    if not code or code not in _LOGIN_ERROR_MESSAGES:
        return None
    return gettext(_LOGIN_ERROR_MESSAGES[code], request=request)


def template_context(request: Request, **kwargs: object) -> dict[str, object]:
    current_user = kwargs.get("current_user")
    context: dict[str, object] = {"request": request, **kwargs}
    context["csrf_token"] = request.session.setdefault("csrf_token", generate_csrf_token())
    context["supported_languages"] = get_supported_languages()
    context["current_language"] = resolve_language(request, user=current_user if isinstance(current_user, User) else None)
    return context


def dev_auth_allowed() -> bool:
    settings = get_settings()
    return settings.dev_auth_enabled and settings.env != "production"


@router.get("/auth/login", name="auth_login", response_class=HTMLResponse)
async def auth_login_page(request: Request):
    settings = get_settings()
    error_code = request.query_params.get("error")
    error_message = _login_error_message(request, error_code)

    if settings.oidc_enabled and not dev_auth_allowed() and not error_message:
        try:
            return await authorize_redirect(request)
        except OAuthError:
            error_message = _login_error_message(request, "sso_failed")

    return templates.TemplateResponse(
        request,
        "auth/login.html",
        template_context(
            request,
            current_user=None,
            oidc_enabled=settings.oidc_enabled,
            dev_auth_enabled=dev_auth_allowed(),
            roles=[role.value for role in Role],
            error_message=error_message,
        ),
    )


@router.get("/auth/oidc")
async def auth_oidc(request: Request):
    try:
        return await authorize_redirect(request)
    except OAuthError:
        return RedirectResponse(url="/auth/login?error=sso_failed", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/auth/callback", name="auth_callback")
async def auth_callback(request: Request, db: Session = Depends(get_db)):
    try:
        oidc_data = await fetch_userinfo(request)
    except OAuthError:
        return RedirectResponse(url="/auth/login?error=sso_failed", status_code=status.HTTP_303_SEE_OTHER)

    userinfo = oidc_data.get("userinfo") or {}
    oidc_subject = userinfo.get("sub")
    display_name = userinfo.get("name") or userinfo.get("preferred_username") or userinfo.get("email") or "User"
    oidc = OIDCUserInfo(
        subject=oidc_subject,
        issuer=userinfo.get("iss"),
        email=userinfo.get("email"),
        display_name=display_name,
        # Nextcloud is the identity provider, so this is the same uid the
        # party sync stores. It is a second lookup key, so changing an address
        # upstream does not lock a working account out.
        preferred_username=userinfo.get("preferred_username"),
    )
    try:
        user = provision_oidc_preapproved_user(db, oidc=oidc)
    except OIDCLoginError as exc:
        return RedirectResponse(url=f"/auth/login?error={exc.code}", status_code=status.HTTP_303_SEE_OTHER)

    request.session["user_id"] = user.id
    request.session.setdefault("csrf_token", generate_csrf_token())
    return RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/auth/logout", dependencies=[Depends(verify_csrf)])
def auth_logout(request: Request):
    request.session.clear()
    return RedirectResponse(url="/auth/login", status_code=status.HTTP_303_SEE_OTHER)


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


@router.get("/api/v1/auth/me", response_model=MeRead)
def me(request: Request, current_user: User = Depends(get_current_user)) -> MeRead:
    token = request.session.setdefault("csrf_token", generate_csrf_token())
    user_payload = UserRead.model_validate(current_user).model_dump()
    return MeRead(**user_payload, csrf_token=token)


@router.post("/api/v1/set-language", dependencies=[Depends(verify_csrf)])
def set_language(request: Request, payload: dict[str, str] | None = Body(default=None)) -> dict[str, str]:
    language = (payload or {}).get("language", "")
    if not set_request_language(request, language):
        raise HTTPException(status_code=400, detail="Unsupported language.")
    return {"language": resolve_language(request)}
