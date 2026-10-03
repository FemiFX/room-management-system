from __future__ import annotations

from botocore.exceptions import ClientError

from hetzner_s3_client import build_client, load_settings


def main() -> None:
    settings = load_settings()
    client = build_client(settings)

    print(f"endpoint={settings.endpoint}")
    print(f"region={settings.region}")
    print(f"bucket={settings.bucket}")
    print(f"prefix={settings.key_prefix}")

    try:
        client.head_bucket(Bucket=settings.bucket)
    except ClientError as exc:
        error = exc.response.get("Error", {})
        raise SystemExit(f"bucket check failed: {error.get('Code')} {error.get('Message')}") from exc

    print("bucket check ok")


if __name__ == "__main__":
    main()

