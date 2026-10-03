from __future__ import annotations

import argparse
import mimetypes
from pathlib import Path

from botocore.exceptions import ClientError

from hetzner_s3_client import build_client, load_settings


def object_exists(client, *, bucket: str, key: str) -> bool:
    try:
        client.head_object(Bucket=bucket, Key=key)
    except ClientError as exc:
        code = (exc.response.get("Error") or {}).get("Code")
        if code in {"404", "NoSuchKey", "NotFound"}:
            return False
        raise
    return True


def migrate(local_root: Path, prefix: str, skip_existing: bool) -> tuple[int, int]:
    settings = load_settings()
    client = build_client(settings)
    normalized_prefix = prefix.strip("/")
    uploaded = 0
    skipped = 0

    for path in local_root.rglob("*"):
        if not path.is_file():
            continue
        relative = path.relative_to(local_root).as_posix()
        key = f"{normalized_prefix}/{relative}" if normalized_prefix else relative
        if skip_existing and object_exists(client, bucket=settings.bucket, key=key):
            skipped += 1
            continue
        mime_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        with path.open("rb") as file_data:
            client.upload_fileobj(
                file_data,
                Bucket=settings.bucket,
                Key=key,
                ExtraArgs={"ContentType": mime_type},
            )
        uploaded += 1
        print(f"uploaded {path} -> s3://{settings.bucket}/{key}")

    return uploaded, skipped


def main() -> None:
    settings = load_settings()
    parser = argparse.ArgumentParser(description="Upload a local directory to Hetzner S3.")
    parser.add_argument("local_root", type=Path)
    parser.add_argument("--prefix", default=settings.key_prefix)
    parser.add_argument("--skip-existing", action="store_true")
    args = parser.parse_args()

    if not args.local_root.is_dir():
        raise SystemExit(f"not a directory: {args.local_root}")

    uploaded, skipped = migrate(args.local_root, args.prefix, args.skip_existing)
    print(f"done uploaded={uploaded} skipped={skipped}")


if __name__ == "__main__":
    main()

