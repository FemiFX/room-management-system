from __future__ import annotations

import hashlib
import io
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from hetzner_s3_client import build_client, load_settings


def build_key(filename: str, prefix: str) -> str:
    suffix = Path(filename).suffix.lower() or ".bin"
    date_path = datetime.now(timezone.utc).strftime("%Y/%m")
    clean_prefix = prefix.strip("/")
    generated = f"{uuid4().hex}{suffix}"
    if clean_prefix:
        return f"{clean_prefix}/{date_path}/{generated}"
    return f"{date_path}/{generated}"


def main() -> None:
    settings = load_settings()
    client = build_client(settings)

    original_filename = "hetzner-s3-smoke-test.txt"
    content = b"Postbuch Hetzner S3 smoke test\n"
    mime_type = "text/plain"
    key = build_key(original_filename, settings.key_prefix)

    client.upload_fileobj(
        Fileobj=io.BytesIO(content),
        Bucket=settings.bucket,
        Key=key,
        ExtraArgs={"ContentType": mime_type},
    )

    digest = hashlib.sha256(content).hexdigest()
    url = client.generate_presigned_url(
        "get_object",
        Params={
            "Bucket": settings.bucket,
            "Key": key,
            "ResponseContentDisposition": f'attachment; filename="{original_filename}"',
            "ResponseContentType": mime_type,
        },
        ExpiresIn=settings.presigned_url_ttl_seconds,
    )

    print(f"bucket={settings.bucket}")
    print(f"key={key}")
    print(f"sha256={digest}")
    print(f"presigned_url={url}")


if __name__ == "__main__":
    main()

