from __future__ import annotations

import time
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import get_settings
from app.storage.minio_client import init_bucket


if __name__ == "__main__":
    settings = get_settings()
    last_error: Exception | None = None
    for _ in range(30):
        try:
            init_bucket()
            print(f"S3 bucket ready: {settings.s3_bucket}")
            break
        except Exception as exc:  # pragma: no cover
            last_error = exc
            print(f"Waiting for S3 bucket {settings.s3_bucket}: {exc}")
            time.sleep(2)
    else:
        raise RuntimeError(f"Failed to verify S3 bucket {settings.s3_bucket}: {last_error}")
