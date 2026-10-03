# Hetzner S3 Integration Kit

This kit is a reusable, minimal version of the object-storage pattern used by
Postbuch.

Use it when you need to plug a Python/FastAPI application into Hetzner Object
Storage through the S3-compatible API.

## What The Kit Demonstrates

- Reading S3 config from environment variables.
- Creating a boto3 S3 client for Hetzner Object Storage.
- Uploading bytes with a generated object key.
- Storing object metadata separately from the binary.
- Generating presigned download URLs.
- Migrating existing local files into a bucket.
- Running a smoke test against the configured bucket.

## Environment

```env
POSTBUCH_S3_ENDPOINT=https://<region>.your-objectstorage.com
POSTBUCH_S3_REGION=fsn1
POSTBUCH_S3_ACCESS_KEY_ID=<hetzner-access-key>
POSTBUCH_S3_SECRET_ACCESS_KEY=<hetzner-secret-key>
POSTBUCH_S3_BUCKET=<bucket-name>
POSTBUCH_S3_KEY_PREFIX=uploads
POSTBUCH_S3_PRESIGNED_URL_TTL_SECONDS=3600
```

For non-Postbuch projects, you can rename these variables. The examples keep the
Postbuch names so they can run inside this repository without changes.

## Install Dependencies

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install boto3
```

Inside Postbuch's Docker image, `boto3` is already installed.

## Files

- `examples/hetzner_s3_client.py`: client/config helper.
- `examples/upload_and_presign.py`: upload bytes and print a presigned URL.
- `examples/check_config.py`: verify environment and bucket access.
- `examples/migrate_directory.py`: upload a local directory into a bucket prefix.
- `examples/fastapi_download_route.py`: FastAPI-style redirect to a presigned
  URL.

## Quick Smoke Test

From the Postbuch container:

```bash
docker compose exec -T web python kits/hetzner_s3_kit/examples/check_config.py
docker compose exec -T web python kits/hetzner_s3_kit/examples/upload_and_presign.py
```

From a local virtualenv:

```bash
python kits/hetzner_s3_kit/examples/check_config.py
python kits/hetzner_s3_kit/examples/upload_and_presign.py
```

The upload example creates a real object in the configured bucket.

## Design Guidance

Keep object storage and application records separate:

- S3 stores the bytes.
- PostgreSQL stores metadata, ownership, workflow state, and references.

Use private buckets plus presigned URLs:

- no public object listing
- no public bucket reads
- short-lived download links
- application authorization remains in the app

Generate object keys yourself:

- do not use user filenames as keys
- include a prefix for environment separation
- include date partitions for browsing and lifecycle rules
- include UUIDs to avoid collisions

Recommended key shape:

```text
<prefix>/<YYYY>/<MM>/<uuid><extension>
```

