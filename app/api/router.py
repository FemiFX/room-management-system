from fastapi import APIRouter, Depends

from app.api.deps import require_staff

from app.api.routes_admin_audit_logs import router as admin_audit_logs_router
from app.api.routes_admin_integrations import router as admin_integrations_router
from app.api.routes_admin_users import router as admin_users_router
from app.api.routes_assets import router as assets_router
from app.api.routes_booking_services import router as booking_services_router
from app.api.routes_bookings import router as bookings_router
from app.api.routes_dashboard import router as dashboard_router
from app.api.routes_documents import router as documents_router
from app.api.routes_notifications import router as notifications_router
from app.api.routes_occupancy import router as occupancy_router
from app.api.routes_portal import router as portal_router
from app.api.routes_public import router as public_router
from app.api.routes_preferences import router as preferences_router
from app.api.routes_spaces import router as spaces_router
from app.api.routes_thumbnails import router as thumbnails_router

api_router = APIRouter()

# Staff-only by default. preferences_router is deliberately excluded: it is
# self-scoped and members need it to set their language.
_staff_only = [Depends(require_staff())]
api_router.include_router(admin_audit_logs_router, dependencies=_staff_only)
api_router.include_router(admin_integrations_router, dependencies=_staff_only)
api_router.include_router(admin_users_router, dependencies=_staff_only)
api_router.include_router(spaces_router, dependencies=_staff_only)
api_router.include_router(thumbnails_router, dependencies=_staff_only)
api_router.include_router(occupancy_router, dependencies=_staff_only)
api_router.include_router(bookings_router, dependencies=_staff_only)
api_router.include_router(booking_services_router, dependencies=_staff_only)
api_router.include_router(assets_router, dependencies=_staff_only)
api_router.include_router(documents_router, dependencies=_staff_only)
api_router.include_router(notifications_router, dependencies=_staff_only)
api_router.include_router(dashboard_router, dependencies=_staff_only)
api_router.include_router(preferences_router)
# Member-facing. Gated inside the router, not by require_staff.
api_router.include_router(portal_router)
# Deliberately unauthenticated -- the public booking surface.
api_router.include_router(public_router)
