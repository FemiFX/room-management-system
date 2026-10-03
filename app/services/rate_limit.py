"""Fixed-window rate limiting for the public surface.

Redis-backed, with an in-process fallback. The fallback matters: failing fully
open when Redis blips means unlimited spam through the public form, and
failing closed takes the form down for everyone. Degrading to a per-process
limit keeps a single attacker capped and keeps the form working.
"""

from __future__ import annotations

import logging
import time
from collections import defaultdict
from threading import Lock

logger = logging.getLogger(__name__)

_fallback: dict[str, list[float]] = defaultdict(list)
_fallback_lock = Lock()


class RateLimited(Exception):
    """Raised when a caller has exceeded its allowance."""

    def __init__(self, retry_after_seconds: int) -> None:
        super().__init__("Too many requests.")
        self.retry_after_seconds = retry_after_seconds


def _fallback_hit(key: str, limit: int, window_seconds: int) -> bool:
    now = time.time()
    with _fallback_lock:
        hits = [stamp for stamp in _fallback[key] if now - stamp < window_seconds]
        hits.append(now)
        _fallback[key] = hits
        return len(hits) > limit


def hit(key: str, *, limit: int, window_seconds: int) -> None:
    """Record one request against ``key``; raise RateLimited when over."""
    try:
        from app.integrations.redis_client import get_redis_client

        client = get_redis_client()
        redis_key = f"rl:{key}:{int(time.time() // window_seconds)}"
        count = client.incr(redis_key)
        if count == 1:
            client.expire(redis_key, window_seconds)
        if count > limit:
            raise RateLimited(window_seconds)
    except RateLimited:
        raise
    except Exception as exc:
        logger.warning("rate limiter falling back to in-process counters: %s", exc)
        if _fallback_hit(key, limit, window_seconds):
            raise RateLimited(window_seconds) from None


def client_ip(request) -> str:
    """Best available client address.

    Behind a reverse proxy `request.client.host` is the proxy, which would put
    every visitor in one bucket and turn the limiter into a self-inflicted
    denial of service. `RMS_TRUSTED_PROXY_COUNT` says how many hops to trust,
    and the address is read from the right-hand end of X-Forwarded-For
    accordingly -- the left-hand entries are attacker-controlled.
    """
    from app.core.config import get_settings

    trusted = get_settings().trusted_proxy_count
    if trusted > 0:
        forwarded = request.headers.get("x-forwarded-for", "")
        chain = [part.strip() for part in forwarded.split(",") if part.strip()]
        if chain:
            index = min(trusted, len(chain))
            return chain[-index]
    client = getattr(request, "client", None)
    return getattr(client, "host", None) or "unknown"


def reset_fallback() -> None:
    """Test hook."""
    with _fallback_lock:
        _fallback.clear()
