from __future__ import annotations

from sqlalchemy import text

from app.db.session import get_session_factory
from app.integrations.redis_client import get_redis_client
from app.storage.minio_client import ensure_bucket_exists


def readiness_report() -> dict[str, str]:
    status = {"database": "down", "redis": "down", "object_storage": "down"}

    db = get_session_factory()()
    try:
        db.execute(text("SELECT 1"))
        status["database"] = "ok"
    finally:
        db.close()

    redis_client = get_redis_client()
    if redis_client.ping():
        status["redis"] = "ok"

    ensure_bucket_exists()
    status["object_storage"] = "ok"

    return status
