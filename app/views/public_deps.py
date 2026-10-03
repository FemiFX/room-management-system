"""Context for anonymous pages.

Public templates must never call `base_admin_context` -- it dereferences
`user.display_name` and `user.role` and builds the staff sidebar. This is the
whole substitute: no user, no navigation, no notifications.
"""

from __future__ import annotations

import hashlib
import hmac

from app.core.config import get_settings
from app.core.i18n import get_supported_languages, language_display_name, resolve_language
from app.core.security import generate_csrf_token
from app.core.time_utils import app_now


def public_context(request, **kwargs) -> dict:
    # Setting the CSRF token is what causes SessionMiddleware to emit the
    # cookie, which is why `verify_csrf` works unmodified for anonymous
    # visitors. The cookie is strictly necessary (CSRF + language) and needs a
    # line in the privacy notice rather than a consent banner.
    csrf_token = request.session.setdefault("csrf_token", generate_csrf_token())
    # user=None on purpose: resolve_language then honours ?lang=, the session
    # and Accept-Language rather than a signed-in user's preference.
    current_language = resolve_language(request, user=None)
    return {
        "request": request,
        "csrf_token": csrf_token,
        "current_language": current_language,
        "supported_languages": get_supported_languages(),
        # The footer carries a copyright year, as the main site's does.
        "current_year": app_now().year,
        "language_options": [
            {"code": code, "label": language_display_name(code)} for code in get_supported_languages()
        ],
        **kwargs,
    }


def hash_ip(address: str | None) -> str | None:
    """Keyed hash of a client address.

    Stored instead of the address itself: enough to correlate abuse from one
    source, not enough to identify a visitor or to be worth stealing.
    """
    if not address:
        return None
    secret = get_settings().secret_key.encode()
    return hmac.new(secret, address.encode(), hashlib.sha256).hexdigest()
