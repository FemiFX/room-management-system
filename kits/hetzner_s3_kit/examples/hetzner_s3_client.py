from __future__ import annotations

import os
from dataclasses import dataclass

import boto3
from botocore.client import Config


@dataclass(frozen=True)
class S3Settings:
    endpoint: str
    region: str
    access_key_id: str
    secret_access_key: str
    bucket: str
    key_prefix: str = "uploads"
    presigned_url_ttl_seconds: int = 3600


def load_settings() -> S3Settings:
    missing: list[str] = []

    def read(name: str, default: str | None = None) -> str:
        value = os.environ.get(name, default)
        if value is None or value == "":
            missing.append(name)
            return ""
        return value

    settings = S3Settings(
        endpoint=read("POSTBUCH_S3_ENDPOINT"),
        region=read("POSTBUCH_S3_REGION"),
        access_key_id=read("POSTBUCH_S3_ACCESS_KEY_ID"),
        secret_access_key=read("POSTBUCH_S3_SECRET_ACCESS_KEY"),
        bucket=read("POSTBUCH_S3_BUCKET"),
        key_prefix=os.environ.get("POSTBUCH_S3_KEY_PREFIX", "uploads"),
        presigned_url_ttl_seconds=int(os.environ.get("POSTBUCH_S3_PRESIGNED_URL_TTL_SECONDS", "3600")),
    )
    if missing:
        raise RuntimeError(f"Missing S3 environment variables: {', '.join(missing)}")
    return settings


def build_client(settings: S3Settings | None = None):
    settings = settings or load_settings()
    return boto3.client(
        "s3",
        endpoint_url=settings.endpoint,
        aws_access_key_id=settings.access_key_id,
        aws_secret_access_key=settings.secret_access_key,
        region_name=settings.region,
        config=Config(signature_version="s3v4"),
    )

