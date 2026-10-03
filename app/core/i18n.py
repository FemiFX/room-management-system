from __future__ import annotations

import gettext as std_gettext
from functools import lru_cache
from pathlib import Path

from fastapi import Request

from app.core.config import get_settings
from app.models.user import User


def get_supported_languages() -> list[str]:
    settings = get_settings()
    return list(dict.fromkeys(settings.supported_languages))


def language_display_name(code: str) -> str:
    labels = {
        "de": "Deutsch",
        "en": "English",
        "fr": "Francais",
        "pt": "Portugues",
        "es": "Espanol",
        "yo": "Yoruba",
        "sw": "Kiswahili",
    }
    return labels.get(code, code.upper())


def get_default_language() -> str:
    settings = get_settings()
    supported = set(get_supported_languages())
    if settings.default_language in supported:
        return settings.default_language
    return next(iter(supported), "de")


def normalize_language(language: str | None) -> str | None:
    if not language:
        return None
    value = language.strip().lower().replace("_", "-")
    base = value.split("-", maxsplit=1)[0]
    return base if base in set(get_supported_languages()) else None


def set_request_language(request: Request, language: str | None) -> bool:
    normalized = normalize_language(language)
    if not normalized:
        return False
    request.session["language"] = normalized
    return True


def resolve_language(request: Request | None, *, user: User | None = None) -> str:
    default_language = get_default_language()
    if request is None:
        return default_language

    path = request.url.path
    is_admin_or_auth_surface = path.startswith("/auth") or (not path.startswith("/api/") and user is not None)
    if is_admin_or_auth_surface and user is not None:
        preferred = normalize_language(getattr(user, "preferred_language", None))
        if preferred:
            return preferred
        return default_language

    # An explicit ?lang= is a deliberate choice made now; a session value is
    # one remembered from earlier. The deliberate one wins, otherwise a
    # link-based language switcher silently does nothing for anyone who has
    # visited before.
    query_language = normalize_language(request.query_params.get("lang"))
    if query_language:
        set_request_language(request, query_language)
        return query_language

    session_language = normalize_language(request.session.get("language"))
    if session_language:
        return session_language

    header_language = _best_language_from_accept_header(request.headers.get("accept-language"))
    if header_language:
        set_request_language(request, header_language)
        return header_language

    set_request_language(request, default_language)
    return default_language


def gettext(message: str, *, request: Request | None = None, user: User | None = None) -> str:
    locale = resolve_language(request, user=user)
    return _load_translations(locale).gettext(message)


@lru_cache(maxsize=32)
def _load_translations(locale: str) -> std_gettext.NullTranslations:
    merged: std_gettext.NullTranslations | None = None
    for directory in _translation_directories():
        loaded = std_gettext.translation(
            domain="messages",
            localedir=str(directory),
            languages=[locale],
            fallback=True,
        )
        if merged is None:
            merged = loaded
        else:
            merged.add_fallback(loaded)
    return merged or std_gettext.NullTranslations()


@lru_cache(maxsize=1)
def _translation_directories() -> tuple[Path, ...]:
    root = Path(__file__).resolve().parents[2]
    settings = get_settings()
    directories: list[Path] = []
    for directory in settings.babel_translation_directories:
        path = Path(directory)
        if not path.is_absolute():
            path = root / path
        directories.append(path)
    return tuple(directories)


def _best_language_from_accept_header(accept_language: str | None) -> str | None:
    if not accept_language:
        return None

    weighted_languages: list[tuple[float, str]] = []
    for part in accept_language.split(","):
        item = part.strip()
        if not item:
            continue
        language = item
        quality = 1.0
        if ";q=" in item:
            language, qvalue = item.split(";q=", maxsplit=1)
            try:
                quality = float(qvalue.strip())
            except ValueError:
                quality = 0.0
        normalized = normalize_language(language)
        if normalized:
            weighted_languages.append((quality, normalized))

    if not weighted_languages:
        return None
    weighted_languages.sort(key=lambda pair: pair[0], reverse=True)
    return weighted_languages[0][1]


def N_(message: str) -> str:
    """Mark a literal for extraction without translating it here.

    For strings defined once at import time and translated per request -- a
    tick list, an enum's labels. `pybabel` reads the source, so it can only
    find a literal at the place it is written; passing a variable to gettext
    leaves the catalogue with nothing to translate and the page in English.
    """
    return message
