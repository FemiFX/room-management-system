# Room Management System

A system for organisations that manage **physical space** — buildings, floors and
rooms; who occupies them and under what lease; who booked which room when; which
physical keys are out and with whom; what equipment each room has; and the
documents attached to all of it.

It carries three surfaces:

- **A public booking site** where anyone can request a room, then retrieve,
  amend or cancel it with a signed link.
- **A member portal** where synced account holders book internal space directly.
- **An admin back office** where staff approve requests, run the calendar, and
  manage rooms, keys, leases, parties and documents.

FastAPI · PostgreSQL · Redis · Celery · MinIO/S3 · OIDC SSO · German + English.

## Try it in about two minutes

```bash
git clone <this-repo> && cd room-management-system
cp .env.example .env
make up             # builds and starts 7 services
make seed-demo      # loads a realistic synthetic dataset
```

- Public booking site → **http://localhost:8001/book**
- Admin → **http://localhost:8001/auth/login**, use the **Developer Login** form

No identity provider, no S3 bucket, no cloud account, no manual migration step,
and no SMTP server — mail is logged rather than sent unless you enable it.

Ports already taken? Every host binding is overridable:

```bash
RMS_API_PORT=18001 RMS_POSTGRES_PORT=15432 make up
```

**How the zero-config login works:** `RMS_DEV_AUTH_ENABLED=true` (the default)
makes the login page render a developer form instead of redirecting to SSO. It is
refused whenever `RMS_ENV=production`, so it cannot follow you into a real
deployment.

## What's interesting in here

### A public booking flow that doesn't need accounts

A visitor submits a request and gets a signed, expiring link. That link is the
only way back in — there is no password and no account. The link carries a
`token_version`, so cancelling or amending a booking can invalidate every link
previously issued for it.

Requests land as `pending`. Staff approve them, and **the conflict check runs at
approval, not submission** — so overlapping requests can queue up freely and
approval is the single point where double-booking is prevented.

### Rate limiting that assumes bad input

The public endpoints are the only unauthenticated write path, so they are
limited on three axes at once — per IP, per email address and per room. The
submitted IP is stored **hashed**, never raw.

One deployment note that is easy to get wrong: `RMS_TRUSTED_PROXY_COUNT`
**must** be set before exposing the form. At `0` behind a proxy, every visitor
shares one rate-limit bucket and the limiter becomes a denial of service against
your own users.

### An OIDC gate that refuses to auto-provision

Most SSO integrations create an account for whoever authenticates. This one
won't. A user must already exist and be active; that first login binds their
`subject` and `issuer`, and every later login must match both. There are **six
distinct deny paths, each separately audited** — so a refusal always says which
rule refused it. See
[`docs/oidc_preapproved_user_gate_handoff.md`](docs/oidc_preapproved_user_gate_handoff.md).

### A production cutover runbook that reconciles row counts

[`docs/prod_cutover_runbook.md`](docs/prod_cutover_runbook.md): staged dumps, a
surgical data-only export of just the inventory tables, an idempotent asset
migration between two S3-compatible providers, sequence resets after a
partial restore (otherwise the first insert collides on the primary key), and
**row-count reconciliation against the numbers captured before the move**.

### Members are scoped, not trusted

A synced account holder would otherwise read every building, party and lease in
the system. `app/core/member_scope.py` narrows what a member can see to what
they actually have, and `tests/test_member_containment.py` pins it.

### Background jobs that answer questions nobody remembers to ask

Celery beat scans for expiring leases, booking conflicts and keys that were
issued and never returned, each feeding the in-app notification system.

## Architecture

| Service | Role |
|---|---|
| `postgres` | PostgreSQL 16, `pg_isready` healthcheck |
| `redis` | Celery broker + rate-limit store |
| `minio` | S3-compatible object storage |
| `minio-init` | One-shot bucket bootstrap; the app waits on it completing |
| `api` | FastAPI on `:8001`, healthcheck on `/health/live` |
| `worker` | Celery worker |
| `scheduler` | Celery beat |

`entrypoint.sh` retries `alembic upgrade head` while Postgres comes up, so
migrations are automatic and there is no first-boot race.

## Tests

```bash
make test
```

289 tests. They cover booking concurrency, member containment, the OIDC deny
paths, the public booking flow, migrations applying to an empty database, and
the i18n fallback chain.

> If you run pytest through `docker compose run`, **rebuild the image first**
> (`docker compose build api`). `tests/` is not bind-mounted, so a stale image
> silently runs an older suite.

## Configuration

Everything is `RMS_`-prefixed and has a working default — no variable hard-fails
on boot.

| Variable | Default | Notes |
|---|---|---|
| `RMS_ENV` | `development` | `production` disables developer login outright |
| `RMS_DEV_AUTH_ENABLED` | `true` | The zero-config login |
| `RMS_OIDC_ENABLED` | `false` | Enable with a real provider |
| `RMS_TRUSTED_PROXY_COUNT` | `0` | **Must be set before exposing the public form** |
| `RMS_PUBLIC_BASE_URL` | localhost | Absolute base for links in email; a worker has no request to derive a host from |
| `RMS_MAIL_ENABLED` | `false` | When off, mail is logged instead of sent |
| `RMS_S3_*` | MinIO | Any S3-compatible provider |
| `RMS_DEFAULT_LANGUAGE` | `de` | `de` and `en` compiled |

### Branding

Name, logo, colours, fonts, footer links, legal pages and the email footer all
come from `RMS_BRAND_*` settings — no template names an organisation, and
re-branding needs no CSS rebuild. Each colour is one hex value, expanded into a
full scale at runtime. See [`docs/branding.md`](docs/branding.md).

### Optional Nextcloud integration

`app/integrations/nextcloud_ocs.py` syncs Nextcloud users into RMS parties and
provisions member logins, with retry and backoff. Entirely gated — it
short-circuits unless URL, admin user and app password are all set.

## Reusable kits

[`kits/`](kits/) holds self-contained extractions of patterns proven here —
audit logging, authentication, i18n, file viewing, S3 and MinIO storage, and the
OIDC pre-approval gate — each with its own README and wiring contract.

## Licence

MIT — see [LICENSE](LICENSE).
