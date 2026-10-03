from __future__ import annotations

from authlib.integrations.starlette_client import OAuth
from fastapi import Request

from authentication_kit.core.config import get_settings

oauth = OAuth()
_registered = False


def get_oauth_client():
    global _registered
    settings = get_settings()
    if not settings.oidc_enabled:
        return None
    if not _registered:
        oauth.register(
            name="oidc",
            server_metadata_url=settings.oidc_server_metadata_url,
            client_id=settings.oidc_client_id,
            client_secret=settings.oidc_client_secret,
            client_kwargs={"scope": settings.oidc_scopes, "timeout": 30},
        )
        _registered = True
    return oauth.create_client("oidc")


async def authorize_redirect(request: Request):
    client = get_oauth_client()
    if client is None:
        raise RuntimeError("OIDC is disabled.")
    return await client.authorize_redirect(request, request.url_for("auth_callback"))


async def fetch_userinfo(request: Request) -> dict:
    client = get_oauth_client()
    if client is None:
        raise RuntimeError("OIDC is disabled.")
    token = await client.authorize_access_token(request)
    userinfo = token.get("userinfo")
    if userinfo is None:
        userinfo = await client.userinfo(token=token)
    return {"token": token, "userinfo": userinfo}

