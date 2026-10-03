from __future__ import annotations

from functools import lru_cache
from typing import Any

from app.core.config import get_settings


@lru_cache
def get_s3_client() -> Any:
    import boto3
    from botocore.client import Config

    settings = get_settings()
    return boto3.client(
        "s3",
        endpoint_url=settings.s3_endpoint_url,
        aws_access_key_id=settings.s3_access_key_id,
        aws_secret_access_key=settings.s3_secret_access_key,
        region_name=settings.s3_region,
        config=Config(
            signature_version="s3v4",
            s3={"addressing_style": settings.s3_addressing_style},
        ),
    )


def _full_key(object_key: str) -> str:
    prefix = get_settings().s3_key_prefix.strip("/")
    if not prefix:
        return object_key
    return f"{prefix}/{object_key}"


def ensure_bucket_exists(bucket_name: str | None = None) -> None:
    settings = get_settings()
    bucket = bucket_name or settings.s3_bucket
    get_s3_client().head_bucket(Bucket=bucket)


def init_bucket() -> None:
    from botocore.exceptions import ClientError

    settings = get_settings()
    client = get_s3_client()
    try:
        client.head_bucket(Bucket=settings.s3_bucket)
        return
    except ClientError as exc:
        code = (exc.response.get("Error") or {}).get("Code")
        if code not in {"404", "NoSuchBucket", "NotFound"}:
            raise
        if not settings.s3_auto_create_bucket:
            raise
    client.create_bucket(Bucket=settings.s3_bucket)


def upload_bytes(*, object_key: str, data: bytes, content_type: str | None = None) -> None:
    settings = get_settings()
    extra: dict[str, Any] = {}
    if content_type:
        extra["ContentType"] = content_type
    get_s3_client().put_object(
        Bucket=settings.s3_bucket,
        Key=_full_key(object_key),
        Body=data,
        **extra,
    )


def get_object_bytes(*, object_key: str) -> tuple[bytes, str | None]:
    """Fetch one object's bytes and content type.

    Used for images the app serves itself rather than handing out a presigned
    URL: a presigned URL expires while the page is still open, and in a
    container-only dev stack its host is not resolvable from the browser.
    """
    response = get_s3_client().get_object(Bucket=get_settings().s3_bucket, Key=_full_key(object_key))
    return response["Body"].read(), response.get("ContentType")


def delete_object(*, object_key: str) -> None:
    from botocore.exceptions import ClientError

    settings = get_settings()
    try:
        get_s3_client().delete_object(Bucket=settings.s3_bucket, Key=_full_key(object_key))
    except ClientError as exc:
        code = (exc.response.get("Error") or {}).get("Code")
        if code in {"404", "NoSuchKey", "NotFound"}:
            return
        raise


def get_presigned_url(*, object_key: str, expiry_seconds: int) -> str:
    settings = get_settings()
    return get_s3_client().generate_presigned_url(
        "get_object",
        Params={"Bucket": settings.s3_bucket, "Key": _full_key(object_key)},
        ExpiresIn=expiry_seconds,
    )
