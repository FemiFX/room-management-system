from functools import lru_cache
from typing import Any

from app.core.config import get_settings


@lru_cache
def get_redis_client() -> Any:
    from redis import Redis

    settings = get_settings()
    return Redis.from_url(settings.redis_url, decode_responses=True)
