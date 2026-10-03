from __future__ import annotations

import secrets


def generate_csrf_token() -> str:
    return secrets.token_urlsafe(32)
