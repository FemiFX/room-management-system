from __future__ import annotations

from fastapi import APIRouter

views_router = APIRouter()

# Import sub-routers after views_router is defined to avoid circular imports
from app.views.views_dashboard import router as dashboard_router  # noqa: E402
from app.views.views_spaces import router as spaces_router  # noqa: E402
from app.views.views_occupancy import router as occupancy_router  # noqa: E402
from app.views.views_assets import router as assets_router  # noqa: E402
from app.views.views_bookings import router as bookings_router  # noqa: E402
from app.views.views_documents import router as documents_router  # noqa: E402
from app.views.views_notifications import router as notifications_router  # noqa: E402
from app.views.views_admin import router as admin_router  # noqa: E402
from app.views.views_integrations import router as integrations_router  # noqa: E402
from app.views.views_preferences import router as preferences_router  # noqa: E402
from app.views.views_portal import router as portal_router  # noqa: E402
from app.views.views_public import router as public_router  # noqa: E402

views_router.include_router(dashboard_router)
views_router.include_router(spaces_router)
views_router.include_router(occupancy_router)
views_router.include_router(assets_router)
views_router.include_router(bookings_router)
views_router.include_router(documents_router)
views_router.include_router(notifications_router)
views_router.include_router(admin_router)
views_router.include_router(integrations_router)
views_router.include_router(preferences_router)
views_router.include_router(portal_router)
views_router.include_router(public_router)
