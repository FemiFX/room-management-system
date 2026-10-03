# MinIO Kit

Comprehensive guide to how MinIO is configured and used in this codebase, with patterns you can copy into other projects.

## What this kit covers
- Infrastructure setup (Docker Compose/Swarm, proxy, ports, health checks).
- Application storage layer (client wrapper, bucket mapping, presigned URLs).
- Object key conventions and bucket layout.
- Upload, download, streaming, and deletion patterns.
- MinIO bucket initialization, migration, and validation scripts.
- CORS configuration options for browser access.
- Specialized flows: thumbnails, captions, TTS audio, model sync, and logging.

## MinIO topology and ports
- `minio` service runs MinIO server with console exposed.
- `minio_proxy` is an Nginx reverse proxy that adds permissive CORS and hides MinIO headers.
- Ports in dev Compose:
  - MinIO console: `http://localhost:9003` (mapped to MinIO console `:9001`).
  - MinIO proxy (CORS-friendly): `http://localhost:9002` (proxy to MinIO `:9000`).

See: `docker-compose.yml`, `docker-stack.yml`, `docker-stack-2.yaml`.

## Buckets and responsibilities
Buckets are defined in `backend/app/storage/minio_client.py`:
- `app-media`: videos, audios, publications.
- `app-captions`: SRT subtitle files.
- `app-thumbnails`: generated image thumbnails (public read).
- `app-tts`: TTS block and document audio.
- `app-models`: large ML model binaries (synced into containers).

Bucket policies:
- `scripts/init_minio_buckets.py` sets `app-thumbnails` to `public-read` and leaves others private.
- The Nginx proxy adds browser CORS headers for GET/HEAD/OPTIONS.

## Object key conventions
Object keys are stored in DB fields as logical paths (no bucket prefix):
- Media: `videos/<filename>`, `audios/<filename>`, `publications/<filename>`.
- Captions: `captions/<media_id>_<lang>.srt`.
- Thumbnails: `thumbnails/<media_id>/thumb_<width>.jpg`.
- TTS:
  - Blocks: `tts/blocks/<voice_id>/<block_hash>.wav`
  - Documents: `tts/documents/<translation_id>_<voice_id>_<doc_hash>.wav`
- Models: `models/<filename>` (with adjacent `.sha256`).

Bucket selection is done by key prefix in `get_bucket_for_object_key()` and by kind in
`get_bucket_for_file_type()`; both live in `backend/app/storage/minio_client.py`.

## Runtime configuration (env vars)
Configured in `backend/app/config.py`:
- `MINIO_ENDPOINT` (default `localhost:9000`)
- `MINIO_ACCESS_KEY` / `MINIO_SECRET_KEY`
- `MINIO_SECURE` (`true|false`)
- `MINIO_PUBLIC_ENDPOINT` (optional host used for public/presigned URLs)
- `MINIO_PUBLIC_SECURE` (`true|false`)

Notes:
- `MINIO_PUBLIC_ENDPOINT` is used to rewrite presigned URLs so clients use the proxy
  or an externally reachable hostname (see `_apply_public_endpoint()`).
- `MINIO_BUCKET_NAME` is present but not used in the current MinIO client wrapper.

## Core storage API (Python)
Implementation lives in `backend/app/storage/minio_client.py`:
- `get_minio_client()` centralizes credentials and secure flag.
- `ensure_bucket_exists()` is called before uploads.
- `upload_file()` and `upload_file_path()` for bytes/streams and local files.
- `download_file()` / `download_file_to_path()` for retrieval.
- `get_object_stream()` for streaming large objects.
- `get_presigned_url()` for temporary access.
- `delete_file()` and `list_objects()`.
- `get_bucket_for_object_key()` and `get_bucket_for_file_type()` for routing.

`backend/app/storage/url_generator.py` provides `storage_url(object_key)` which:
- Returns direct http(s) URLs unchanged.
- Passes through `/static/...` paths (legacy/static usage).
- Normalizes `static/uploads` paths to MinIO keys.
- Generates presigned URLs with a configurable expiry.

## App-level usage patterns

### Media upload (API)
`backend/app/api/media.py` writes uploads to MinIO:
- Generates a key `videos/<filename>` or `audios/<filename>`.
- Calls `upload_file_path()` to store in `app-media`.
- Stores the key in `MediaContent.object_key`.

### Publications upload (Admin UI)
`backend/app/views/routes.py` uploads publications and optional thumbnails:
- Publications go to `app-media` with `publications/<filename>`.
- Thumbnails go to `app-thumbnails`.

### Thumbnails
`backend/app/services/thumbnailer.py`:
- Produces multiple widths and uploads each to `app-thumbnails`.
- Returns keys for DB storage (best candidate is stored in `MediaContent.thumbnail_key`).

### Captions (SRT)
`backend/app/tasks/transcription.py`:
- Uploads SRT text to `app-captions`.
- Stores key in `Transcript.srt_object_key`.

`backend/app/views/public.py`:
- Downloads SRT from MinIO, converts to VTT, returns inline response.

### TTS audio
`backend/app/tasks/tts.py`:
- Saves block/doc audio to temp disk and uploads to `app-tts`.
- Stores keys in `TTSBlockAudio.audio_key` and `TTSDocumentAudio.audio_key`.

`backend/app/api/content.py`:
- Returns `storage_url()` for TTS audio in API responses.
- Deletes MinIO objects when TTS data is removed.

### PDF extraction
`backend/app/tasks/pdf.py` downloads publications from MinIO to a temp dir for processing.

### Model sync
`scripts/upload_model_to_minio.py` uploads a model + `.sha256` to `app-models`.
`scripts/sync_models_from_minio.py` downloads and verifies checksums into a local cache.

### Logging (Loki)
`LOGGING.md` documents MinIO as Loki’s backend storage.
`scripts/init-loki-bucket.sh` creates `loki-chunks`.

## Bucket initialization and migration

### Initialize buckets
Preferred: `scripts/init_minio_buckets.py` (Python client).
Alternatives:
- `scripts/init_minio_buckets.sh` (uses `mc`).
- Docker compose service `app_bucket_init` (see `scripts/README_BUCKET_INIT.md`).

### Migration from static storage
`scripts/migrate_to_minio.py`:
- Scans `backend/app/static/uploads/`.
- Uploads to MinIO with normalized keys.
- Updates DB object_key fields to remove `/static/uploads/`.

Reference doc: `MIGRATION_TO_MINIO.md`.

## CORS configuration
Three approaches exist:
- Nginx proxy headers in `nginx/minio-cors.conf` (used by `minio_proxy`).
- MinIO bucket CORS via Python client: `scripts/set_minio_cors.py`.
- MinIO bucket CORS via boto3: `scripts/set_minio_cors_boto3.py`.

There are example CORS policy files in `minio/cors.json` and `minio/cors.xml`.

## Validation and health checks
`scripts/test_minio_connection.py`:
- Connects, ensures buckets, tests upload/download, presigned URL.

MinIO healthcheck in Docker:
- `curl -f http://localhost:9000/minio/health/live`

## Known exceptions (still local disk)
`backend/app/api/uploads.py` (editor embeds) still writes to
`backend/app/static/uploads/...` and returns `/static/...` URLs.
If you want fully MinIO-backed storage, update these endpoints to use
`upload_file_path()` and store keys in MinIO.

## Implementation checklist for another project
1) Add MinIO service + proxy (see `docker-compose.yml`).
2) Add config env vars (see `backend/app/config.py`).
3) Copy `backend/app/storage/` (minio client + URL helper).
4) Define bucket names and key conventions for your domain.
5) Replace file upload handlers with `upload_file_path()` + object key storage.
6) Replace file access in views/templates with `storage_url()`.
7) Add bucket init scripts and run them in deploy pipelines.
8) Add CORS policy (proxy or bucket CORS).
9) For migrations, run `scripts/migrate_to_minio.py` and verify.

## Source references
- Storage client: `backend/app/storage/minio_client.py`
- URL helper: `backend/app/storage/url_generator.py`
- Config: `backend/app/config.py`
- Docker: `docker-compose.yml`, `docker-stack.yml`, `docker-stack-2.yaml`
- Proxy: `nginx/minio-cors.conf`
- Init scripts: `scripts/init_minio_buckets.py`, `scripts/init_minio_buckets.sh`
- Migration: `scripts/migrate_to_minio.py`, `MIGRATION_TO_MINIO.md`
- CORS tools: `scripts/set_minio_cors.py`, `scripts/set_minio_cors_boto3.py`
- Validation: `scripts/test_minio_connection.py`
- Model sync: `scripts/upload_model_to_minio.py`, `scripts/sync_models_from_minio.py`
