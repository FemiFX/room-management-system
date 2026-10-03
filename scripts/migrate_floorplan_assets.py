"""
Copy floorplan/image bytes referenced by floors.floorplan_object_key and
floors.image_object_key from the dev source bucket to the production
destination bucket, applying the destination key prefix.

Reads the dev DB to enumerate keys, downloads from SRC_S3_*, uploads to
DST_S3_* at "<DST_S3_KEY_PREFIX>/<original_key>". Idempotent: re-runs skip
keys that already exist at the destination.

Required env vars:
    DB_URL                       Source Postgres connection string
    SRC_S3_ENDPOINT_URL          e.g. http://minio:9000
    SRC_S3_REGION                e.g. us-east-1
    SRC_S3_ACCESS_KEY_ID
    SRC_S3_SECRET_ACCESS_KEY
    SRC_S3_BUCKET                e.g. rms-dev (or the legacy 'rms-floorplans')
    SRC_S3_KEY_PREFIX            e.g. rms (empty if source has no prefix)
    SRC_S3_ADDRESSING_STYLE      path | virtual (default: path)
    DST_S3_ENDPOINT_URL          e.g. https://<region>.your-objectstorage.com
    DST_S3_REGION                e.g. fsn1
    DST_S3_ACCESS_KEY_ID
    DST_S3_SECRET_ACCESS_KEY
    DST_S3_BUCKET                e.g. your-bucket-name
    DST_S3_KEY_PREFIX            e.g. rms
    DST_S3_ADDRESSING_STYLE      path | virtual (default: virtual)
"""
from __future__ import annotations

import os
import sys
from dataclasses import dataclass

import boto3
from botocore.client import Config
from botocore.exceptions import ClientError
from sqlalchemy import create_engine, text


@dataclass(frozen=True)
class S3Endpoint:
    label: str
    endpoint_url: str
    region: str
    access_key_id: str
    secret_access_key: str
    bucket: str
    key_prefix: str
    addressing_style: str


def _read_endpoint(prefix: str, default_addressing: str) -> S3Endpoint:
    def must(name: str) -> str:
        value = os.environ.get(f"{prefix}_{name}")
        if not value:
            print(f"missing env: {prefix}_{name}", file=sys.stderr)
            sys.exit(2)
        return value

    return S3Endpoint(
        label=prefix,
        endpoint_url=must("S3_ENDPOINT_URL"),
        region=must("S3_REGION"),
        access_key_id=must("S3_ACCESS_KEY_ID"),
        secret_access_key=must("S3_SECRET_ACCESS_KEY"),
        bucket=must("S3_BUCKET"),
        key_prefix=os.environ.get(f"{prefix}_S3_KEY_PREFIX", "").strip("/"),
        addressing_style=os.environ.get(f"{prefix}_S3_ADDRESSING_STYLE", default_addressing),
    )


def _client(endpoint: S3Endpoint):
    return boto3.client(
        "s3",
        endpoint_url=endpoint.endpoint_url,
        aws_access_key_id=endpoint.access_key_id,
        aws_secret_access_key=endpoint.secret_access_key,
        region_name=endpoint.region,
        config=Config(signature_version="s3v4", s3={"addressing_style": endpoint.addressing_style}),
    )


def _full_key(endpoint: S3Endpoint, logical_key: str) -> str:
    if not endpoint.key_prefix:
        return logical_key
    return f"{endpoint.key_prefix}/{logical_key}"


def _exists(client, bucket: str, key: str) -> bool:
    try:
        client.head_object(Bucket=bucket, Key=key)
    except ClientError as exc:
        code = (exc.response.get("Error") or {}).get("Code")
        if code in {"404", "NoSuchKey", "NotFound"}:
            return False
        raise
    return True


def _logical_keys_from_db(db_url: str) -> list[str]:
    engine = create_engine(db_url)
    with engine.connect() as conn:
        rows = conn.execute(text(
            "SELECT floorplan_object_key, image_object_key FROM floors"
        )).all()
    seen: set[str] = set()
    out: list[str] = []
    for floorplan_key, image_key in rows:
        for key in (floorplan_key, image_key):
            if key and key not in seen:
                seen.add(key)
                out.append(key)
    return out


def main() -> None:
    db_url = os.environ.get("DB_URL")
    if not db_url:
        print("missing env: DB_URL", file=sys.stderr)
        sys.exit(2)

    src = _read_endpoint("SRC", default_addressing="path")
    dst = _read_endpoint("DST", default_addressing="virtual")

    src_client = _client(src)
    dst_client = _client(dst)

    logical_keys = _logical_keys_from_db(db_url)
    print(f"found {len(logical_keys)} floorplan/image keys in floors")

    copied = 0
    skipped_existing = 0
    skipped_missing = 0
    for logical_key in logical_keys:
        src_key = _full_key(src, logical_key)
        dst_key = _full_key(dst, logical_key)

        if _exists(dst_client, dst.bucket, dst_key):
            skipped_existing += 1
            print(f"skip (exists at dst): {dst_key}")
            continue

        try:
            obj = src_client.get_object(Bucket=src.bucket, Key=src_key)
        except ClientError as exc:
            code = (exc.response.get("Error") or {}).get("Code")
            if code in {"404", "NoSuchKey", "NotFound"}:
                skipped_missing += 1
                print(f"skip (not in src): {src_key}")
                continue
            raise

        body = obj["Body"].read()
        content_type = obj.get("ContentType")
        extra = {"ContentType": content_type} if content_type else {}
        dst_client.put_object(Bucket=dst.bucket, Key=dst_key, Body=body, **extra)
        copied += 1
        print(f"copied src://{src.bucket}/{src_key} -> dst://{dst.bucket}/{dst_key} ({len(body)} bytes)")

    print(f"done copied={copied} skipped_existing={skipped_existing} skipped_missing={skipped_missing}")


if __name__ == "__main__":
    main()
