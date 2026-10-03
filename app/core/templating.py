from pathlib import Path

from fastapi.templating import Jinja2Templates
from jinja2 import pass_context

from app.core.i18n import gettext, get_supported_languages, resolve_language

templates = Jinja2Templates(directory=str(Path(__file__).resolve().parents[1] / "templates"))


@pass_context
def template_gettext(context, message: str) -> str:
    request = context.get("request")
    current_user = context.get("current_user")
    if request is None:
        return gettext(message)
    return gettext(message, request=request, user=current_user)


@pass_context
def template_current_language(context) -> str:
    request = context.get("request")
    current_user = context.get("current_user")
    return resolve_language(request, user=current_user)


def local_datetime(value, fmt: str = "%d.%m.%Y %H:%M") -> str:
    """Format a datetime in the application timezone.

    Templates used to call `.strftime()` on the column directly and compare it
    against an aware `now`. SQLite drops timezone information, so those
    comparisons raised TypeError there, and on PostgreSQL the same code
    rendered UTC rather than local time. Going through to_app_tz fixes both.
    """
    if value is None:
        return ""
    from app.core.time_utils import to_app_tz

    return to_app_tz(value).strftime(fmt)


@pass_context
def template_is_past(context, value) -> bool:
    from app.core.time_utils import app_now, to_app_tz

    if value is None:
        return False
    return to_app_tz(value) < app_now()


templates.env.filters["local_datetime"] = local_datetime
templates.env.globals["is_past"] = template_is_past
templates.env.globals["_"] = template_gettext
templates.env.globals["current_language"] = template_current_language
templates.env.globals["supported_languages"] = get_supported_languages


def asset_version(path: str) -> str:
    """A cache key for a built asset, taken from its modification time.

    The stylesheet is a build artefact behind a stable URL, so a browser that
    fetched it once keeps serving that copy -- which is how a rebuilt page
    ends up looking broken for the person reviewing it and fine for everyone
    else. The mtime changes when the build does; nothing else has to.
    """
    from pathlib import Path as _Path

    asset = _Path(__file__).resolve().parents[1] / "static" / path
    try:
        return str(int(asset.stat().st_mtime))
    except OSError:
        return "0"


templates.env.globals["asset_version"] = asset_version


class _LazyBranding:
    """Resolve branding on first attribute access rather than at import, so a
    test or process that sets RMS_BRAND_* after this module loads still sees
    its own values."""

    def __getattr__(self, item):
        from app.core.branding import get_branding

        return getattr(get_branding(), item)


templates.env.globals["brand"] = _LazyBranding()
