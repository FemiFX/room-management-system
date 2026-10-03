from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from app.api.router import api_router
from app.api.routes_auth import router as auth_router
from app.core.config import get_settings
from app.core.member_scope import MemberScopeMiddleware
from app.services.health import readiness_report


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title=settings.app_name)

    # Registration order is load-bearing: Starlette builds the stack in
    # reverse, so the LAST add_middleware call is the outermost. MemberScope
    # reads request.session, so it must be added BEFORE SessionMiddleware in
    # order to run INSIDE it.
    app.add_middleware(MemberScopeMiddleware)

    app.add_middleware(
        SessionMiddleware,
        secret_key=settings.secret_key,
        session_cookie=settings.session_cookie_name,
        same_site="lax",
        https_only=settings.session_secure,
    )

    if settings.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_origins,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    static_dir = Path(__file__).resolve().parent / "static"
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    app.include_router(auth_router)
    app.include_router(api_router, prefix="/api/v1")

    from app.views import views_router
    app.include_router(views_router)

    @app.get("/health/live")
    def health_live() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/health/ready")
    def health_ready() -> dict[str, object]:
        report = readiness_report()
        overall = "ok" if all(value == "ok" for value in report.values()) else "degraded"
        return {"status": overall, "checks": report}

    return app
