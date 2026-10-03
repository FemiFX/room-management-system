# Production Cutover Runbook

End-to-end steps for taking the curated dev inventory (buildings, floors, rooms, keys, room equipment, internet connections) and the floor-plan/image bytes from local MinIO into a fresh production stack on Hetzner.

Outcome:
- Prod Postgres holds only your real inventory plus one super-admin user.
- Prod object storage (`your-bucket-name` on Hetzner, prefix `rms/`) holds the floor-plan/image bytes referenced by the imported `floors` rows.
- All test users, parties, leases, bookings, key assignments, documents, audit logs, and notifications are absent.

Throughout this doc:
- `[DEV]` = run on the developer machine where the local `docker compose` stack is running.
- `[PROD]` = run on the Hetzner VM where the production `docker compose` stack will run.

---

## Prerequisites

- Hetzner Object Storage bucket `your-bucket-name` already exists with an access key + secret.
- Production VM with Docker installed.
- The repo cloned on the prod VM at the same revision as dev (the cutover commit including `docker-compose.prod.yml`).
- Production `.env` file prepared on the VM. At minimum:

  ```env
  RMS_ENV=production
  RMS_SECRET_KEY=<long-random-string>
  RMS_DATABASE_URL=postgresql+psycopg://rms:<strong-password>@postgres:5432/rms
  RMS_SESSION_SECURE=true
  RMS_DEV_AUTH_ENABLED=false

  RMS_OIDC_ENABLED=true
  RMS_OIDC_SERVER_METADATA_URL=<your IdP metadata URL>
  RMS_OIDC_CLIENT_ID=<prod client id>
  RMS_OIDC_CLIENT_SECRET=<prod client secret>

  RMS_S3_ENDPOINT_URL=https://<region>.your-objectstorage.com
  RMS_S3_REGION=fsn1
  RMS_S3_ACCESS_KEY_ID=<hetzner access key>
  RMS_S3_SECRET_ACCESS_KEY=<hetzner secret>
  RMS_S3_BUCKET=your-bucket-name
  RMS_S3_KEY_PREFIX=rms
  RMS_S3_ADDRESSING_STYLE=virtual
  ```

- Postgres credentials for the prod stack: set `POSTGRES_PASSWORD` in a prod-only env block (or in the prod `.env`), and make sure `RMS_DATABASE_URL` matches.

---

## Step 1 — `[DEV]` Take a full safety snapshot

This is your "oh-no" rollback if anything goes sideways. Not loaded into prod — just stored for safety.

```bash
mkdir -p backups
docker compose exec -T postgres pg_dump -U rms rms \
    > backups/rms-dev-full-$(date +%Y%m%d-%H%M%S).sql
ls -lh backups/
```

Verify the file is non-empty (a few MB at minimum) and the last lines look like a normal `pg_dump` (`-- PostgreSQL database dump complete`).

---

## Step 2 — `[DEV]` Export only the inventory tables

Data-only dump of the six tables that should survive the cutover. Order in the file follows FK dependencies (buildings → floors → rooms → keys, plus room_equipment & internet_connections which depend on rooms).

```bash
docker compose exec -T postgres pg_dump -U rms --data-only \
    --table=buildings \
    --table=floors \
    --table=rooms \
    --table=keys \
    --table=room_equipment \
    --table=internet_connections \
    rms > backups/rms-inventory-$(date +%Y%m%d-%H%M%S).sql

ls -lh backups/rms-inventory-*.sql
```

Sanity-check the dump:

```bash
grep -c "^COPY public.buildings"          backups/rms-inventory-*.sql   # expect 1
grep -c "^COPY public.floors"             backups/rms-inventory-*.sql   # expect 1
grep -c "^COPY public.rooms"              backups/rms-inventory-*.sql   # expect 1
grep -c "^COPY public.keys"               backups/rms-inventory-*.sql   # expect 1
grep -c "^COPY public.room_equipment"     backups/rms-inventory-*.sql   # expect 1
grep -c "^COPY public.internet_connections" backups/rms-inventory-*.sql # expect 1
```

Capture row counts you should see on the prod side after import:

```bash
docker compose exec -T postgres psql -U rms -d rms -c "
SELECT
  (SELECT count(*) FROM buildings)           AS buildings,
  (SELECT count(*) FROM floors)              AS floors,
  (SELECT count(*) FROM rooms)               AS rooms,
  (SELECT count(*) FROM keys)                AS keys,
  (SELECT count(*) FROM room_equipment)      AS room_equipment,
  (SELECT count(*) FROM internet_connections) AS internet_connections;
"
```

Write these counts down — you'll compare against prod in Step 7.

---

## Step 3 — `[DEV]` Migrate floor-plan / image bytes to Hetzner

`floors.floorplan_object_key` and `floors.image_object_key` reference objects that today live in dev MinIO. Copy them to `your-bucket-name` under the `rms/` prefix so the imported `floors` rows on prod will resolve.

The script reads two sets of S3 env vars (`SRC_S3_*` for dev MinIO, `DST_S3_*` for Hetzner) and the dev `DB_URL`. It is idempotent — safe to re-run.

```bash
docker compose exec -T \
    -e DB_URL="postgresql+psycopg://rms:rms@postgres:5432/rms" \
    -e SRC_S3_ENDPOINT_URL="http://minio:9000" \
    -e SRC_S3_REGION="us-east-1" \
    -e SRC_S3_ACCESS_KEY_ID="minioadmin" \
    -e SRC_S3_SECRET_ACCESS_KEY="minioadmin" \
    -e SRC_S3_BUCKET="rms-dev" \
    -e SRC_S3_KEY_PREFIX="rms" \
    -e SRC_S3_ADDRESSING_STYLE="path" \
    -e DST_S3_ENDPOINT_URL="https://<region>.your-objectstorage.com" \
    -e DST_S3_REGION="fsn1" \
    -e DST_S3_ACCESS_KEY_ID="<hetzner access key>" \
    -e DST_S3_SECRET_ACCESS_KEY="<hetzner secret>" \
    -e DST_S3_BUCKET="your-bucket-name" \
    -e DST_S3_KEY_PREFIX="rms" \
    -e DST_S3_ADDRESSING_STYLE="virtual" \
    api python scripts/migrate_floorplan_assets.py
```

Expected output ends with `done copied=N skipped_existing=0 skipped_missing=0`. Re-running should report `skipped_existing=N`.

Verify in the Hetzner console: objects appear under `your-bucket-name/rms/floorplans/...`.

---

## Step 4 — `[PROD]` Bring up the stack and let migrations run

On the prod VM, with `.env` and `docker-compose.prod.yml` in place:

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build postgres redis
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d api
docker compose -f docker-compose.yml -f docker-compose.prod.yml logs -f api
```

Wait for `Uvicorn running on http://0.0.0.0:8001` (API serving and `alembic upgrade head` finished). Then **stop the api** before importing data so it doesn't write notifications/audit rows in the middle of the load:

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml stop api
```

Confirm the schema is empty:

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml exec -T postgres \
    psql -U rms -d rms -c "
SELECT
  (SELECT count(*) FROM buildings) AS buildings,
  (SELECT count(*) FROM users)     AS users,
  (SELECT count(*) FROM rooms)     AS rooms,
  (SELECT count(*) FROM keys)      AS keys;
"
```

All four should be `0`.

---

## Step 5 — `[PROD]` Verify Hetzner is reachable from the prod stack

Sanity check before loading data:

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml run --rm \
    --entrypoint python api scripts/init_minio_buckets.py
```

Expected: `S3 bucket ready: your-bucket-name`. (Because `RMS_S3_AUTO_CREATE_BUCKET` is **not** set in prod, the script will only `head_bucket`; if the bucket is missing or credentials are wrong, this fails immediately.)

---

## Step 6 — `[PROD]` Copy the inventory dump onto the box and load it

From your dev machine, ship the inventory dump to the prod VM (substitute hostname):

```bash
# [DEV]
scp backups/rms-inventory-YYYYMMDD-HHMMSS.sql user@prod-vm:/tmp/rms-inventory.sql
scp scripts/reset_sequences.sql                user@prod-vm:/tmp/reset_sequences.sql
```

On the prod VM, copy them into the Postgres container and load:

```bash
# [PROD]
docker compose -f docker-compose.yml -f docker-compose.prod.yml cp \
    /tmp/rms-inventory.sql postgres:/tmp/rms-inventory.sql
docker compose -f docker-compose.yml -f docker-compose.prod.yml cp \
    /tmp/reset_sequences.sql postgres:/tmp/reset_sequences.sql

docker compose -f docker-compose.yml -f docker-compose.prod.yml exec -T postgres \
    psql -U rms -d rms -v ON_ERROR_STOP=1 -f /tmp/rms-inventory.sql

docker compose -f docker-compose.yml -f docker-compose.prod.yml exec -T postgres \
    psql -U rms -d rms -v ON_ERROR_STOP=1 -f /tmp/reset_sequences.sql
```

The `setval` script ensures the next inserted row in each table gets an id higher than any imported row — without it, the very first new room/key insert would collide on the primary key.

---

## Step 7 — `[PROD]` Verify the data landed

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml exec -T postgres \
    psql -U rms -d rms -c "
SELECT
  (SELECT count(*) FROM buildings)            AS buildings,
  (SELECT count(*) FROM floors)               AS floors,
  (SELECT count(*) FROM rooms)                AS rooms,
  (SELECT count(*) FROM keys)                 AS keys,
  (SELECT count(*) FROM room_equipment)       AS room_equipment,
  (SELECT count(*) FROM internet_connections) AS internet_connections,
  (SELECT count(*) FROM users)                AS users,
  (SELECT count(*) FROM parties)              AS parties,
  (SELECT count(*) FROM leases)               AS leases,
  (SELECT count(*) FROM bookings)             AS bookings,
  (SELECT count(*) FROM documents)            AS documents,
  (SELECT count(*) FROM audit_log)            AS audit_log,
  (SELECT count(*) FROM key_assignments)      AS key_assignments,
  (SELECT count(*) FROM notifications)        AS notifications;
"
```

Expected:
- The first six counts match what you wrote down in Step 2.
- The remaining eight are all `0`.

Also verify the sequences were bumped (next insert id should exceed `MAX(id)`):

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml exec -T postgres \
    psql -U rms -d rms -c "
SELECT
  last_value AS rooms_next_id_minus_one,
  (SELECT MAX(id) FROM rooms) AS rooms_max_id
FROM rooms_id_seq;
"
```

`last_value` should be one greater than `MAX(id)` (because we used `setval(..., MAX(id)+1, false)`).

---

## Step 8 — `[PROD]` Seed the first super-admin

Bring the API back up and seed the super-admin who will be your first OIDC login:

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml start api

docker compose -f docker-compose.yml -f docker-compose.prod.yml exec api \
    python -m app.cli seed-super-admin \
    --email you@yourdomain.com \
    --display-name "Your Name"
```

Expected: `Created super_admin user id=1 email=you@yourdomain.com`.

---

## Step 9 — `[PROD]` End-to-end smoke test

1. Visit the prod URL, log in via OIDC with the email you seeded.
2. Open the dashboard — your buildings/floors/rooms/keys should be visible.
3. Open a room that has a floor with a floor plan — the image should render (this exercises the boto3 client → presigned URL → Hetzner round-trip end-to-end).
4. Upload a small test document on a room (proves write path to Hetzner). Then delete it (proves delete path).
5. In the Hetzner console, confirm the test object appeared at `your-bucket-name/rms/documents/...` and disappeared after delete.
6. Check `/health/ready` returns `{"status":"ok",...}` with `object_storage: ok`.

---

## Rollback

If anything in steps 4–8 goes wrong and you want to start over from a blank prod DB:

```bash
# [PROD]
docker compose -f docker-compose.yml -f docker-compose.prod.yml down
docker volume rm room_management_system_postgres_data
# Then start again from Step 4.
```

Hetzner objects copied in Step 3 can stay; re-running the migrate script is idempotent. To wipe the `rms/` prefix instead, use the Hetzner console or:

```bash
aws s3 rm s3://your-bucket-name/rms/ --recursive \
    --endpoint-url https://<region>.your-objectstorage.com \
    --region fsn1
```

The full safety dump from Step 1 is your last-resort restore for the dev DB — never load it into prod (it contains the test users you're trying to leave behind).
