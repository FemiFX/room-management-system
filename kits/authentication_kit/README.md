# Authentication Kit: OIDC + Admin Fallback (Extracted from Postbuch)

> **Note on `reference_snapshot/`**
>
> Some kits originally shipped a `reference_snapshot/` directory holding verbatim
> copies of the upstream files the kit was extracted from. Those snapshots are not
> part of this public release — they contained source from unrelated private
> projects. Paths of the form `reference_snapshot/...` referenced below describe the
> original layout and are not present in this repository.


This kit captures the exact authentication pattern used in this repository and packages it for reuse in a new FastAPI project.

## Goal

Provide a reusable, implementation-level auth baseline with:

- OIDC login via Authlib
- Session-cookie auth with Starlette `SessionMiddleware`
- First-login user provisioning from OIDC claims
- Admin bootstrap fallback via OIDC email allowlist
- Local developer fallback login (non-production only)
- Role checks + CSRF protection patterns
- Test cases for critical provisioning behavior

## What Is Included

This kit has two layers:

1. `reference_snapshot/`
Direct source copies from this codebase (`postbuch`). Use this when you want the exact proven implementation.

2. `blueprint/`
A portable package named `authentication_kit` with the same auth behavior but trimmed to auth-focused modules so an AI/codegen agent can transplant it quickly.

## Directory Layout

```text
kits/authentication_kit/
  README.md
  examples/
    DROP_IN_PATCH_PLAN.md
    users_and_audit_schema.sql
  reference_snapshot/
    ORIGIN.md
    .env.example
    docs/operations/
      local_setup.md
      oidc_setup.md
    postbuch/
      api/deps.py
      api/routes.py
      auth/oidc.py
      core/config.py
      core/utils.py
      db/base.py
      db/session.py
      main.py
      models/audit_log.py
      models/enums.py
      models/mixins.py
      models/user.py
      services/audit.py
      services/users.py
      templates/auth/login.html
    tests/test_users.py
  blueprint/
    .env.example
    requirements.txt
    examples/main.py
    tests/test_users.py
    authentication_kit/
      __init__.py
      api/
        __init__.py
        deps.py
        routes_auth.py
      auth/
        __init__.py
        oidc.py
      core/
        __init__.py
        config.py
        security.py
        templating.py
      db/
        __init__.py
        base.py
        session.py
      models/
        __init__.py
        audit_log.py
        enums.py
        mixins.py
        user.py
      schemas/
        __init__.py
        common.py
        user.py
      services/
        __init__.py
        audit.py
        users.py
      templates/auth/login.html
```

## Behavior Contract (Exact Pattern)

### 1. OIDC Login Flow

- `GET /auth/login`
  - If `oidc_enabled=true` and dev fallback is not allowed: auto-redirect to OIDC provider.
  - Otherwise render login page with both OIDC and developer fallback options.
- `GET /auth/oidc`: explicit OIDC redirect endpoint.
- `GET /auth/callback`
  - Exchanges code for token
  - Pulls `userinfo` (`sub`, `name`/`preferred_username`, `email`, `iss`)
  - Provisions/updates local user
  - Stores `session["user_id"]`
  - Ensures `session["csrf_token"]`
  - Redirects to `/`

### 2. Admin Fallback (Bootstrap)

Admin fallback exists in two layers:

- OIDC allowlist bootstrap:
  - `POSTBUCH_OIDC_ADMIN_EMAILS` is a comma-separated allowlist.
  - On first OIDC login, if `userinfo.email` is in allowlist, role is `super_admin`.
  - Else first-login role is `viewer`.
- Local non-production fallback:
  - `POSTBUCH_DEV_AUTH_ENABLED=true` and `env != production` unlocks `/auth/dev-login`.
  - Dev form defaults to `admin@example.com` and role `super_admin`.

### 3. Session + CSRF Model

- Session cookie set via `SessionMiddleware`.
- Logged-in identity tracked in `session["user_id"]`.
- CSRF token tracked in `session["csrf_token"]`.
- `verify_csrf` enforces token on `POST`/`PATCH`/`DELETE`:
  - header: `x-csrf-token`
  - or form field: `csrf_token`

### 4. Authorization Model

- `get_current_user`: resolves active session user, clears session if invalid/inactive.
- `require_role(Role...)`: enforces route-level RBAC.
- Roles:
  - `super_admin`
  - `admin`
  - `editor`
  - `viewer`

## Key Files and Why They Matter

- `reference_snapshot/postbuch/auth/oidc.py`
  - Authlib OIDC client registration and callbacks.
- `reference_snapshot/postbuch/services/users.py`
  - First-login provisioning logic and admin allowlist fallback.
- `reference_snapshot/postbuch/api/deps.py`
  - Current user resolution, role requirements, CSRF checks.
- `reference_snapshot/postbuch/api/routes.py`
  - Real route integration for login/callback/logout/dev-login.
- `reference_snapshot/postbuch/main.py`
  - Session middleware wiring.
- `reference_snapshot/tests/test_users.py`
  - Verified behavior for first login, repeat login, and dev fallback provisioning.

## Environment Variables

Use these as the auth contract for any new project adopting this kit:

- `POSTBUCH_SECRET_KEY`
- `POSTBUCH_SESSION_COOKIE_NAME`
- `POSTBUCH_OIDC_ENABLED`
- `POSTBUCH_OIDC_SERVER_METADATA_URL`
- `POSTBUCH_OIDC_CLIENT_ID`
- `POSTBUCH_OIDC_CLIENT_SECRET`
- `POSTBUCH_OIDC_SCOPES` (default: `openid profile email`)
- `POSTBUCH_OIDC_ADMIN_EMAILS` (comma-separated)
- `POSTBUCH_DEV_AUTH_ENABLED`
- `POSTBUCH_ENV`

Reference examples:

- `reference_snapshot/.env.example`
- `blueprint/.env.example`

## FastAPI Integration Steps (New Project)

1. Copy `blueprint/authentication_kit` into your new project (or vendor it as package).
2. Install `blueprint/requirements.txt` dependencies.
3. Ensure your app includes `SessionMiddleware` before route use.
4. Include `authentication_kit.api.routes_auth.router` in your app router.
5. Add `authentication_kit/templates` path to your template search path.
6. Create `users` and `audit_log` schema (see `examples/users_and_audit_schema.sql`).
7. Set environment variables, especially OIDC metadata URL, client ID/secret, and admin allowlist.
8. Test:
   - first login as allowlisted email -> `super_admin`
   - first login as non-allowlisted email -> `viewer`
   - repeat login updates same user (no duplicates)
   - dev-login disabled in production env

## Security Notes

These are inherited from the existing implementation and should be reviewed in the new project:

- `https_only=False` in `SessionMiddleware` is suitable for local/dev but should be `True` behind TLS in production.
- Add stricter cookie settings (`secure`, `httponly`, `samesite`) aligned with your deployment.
- Validate issuer/audience behavior according to your OIDC provider defaults.
- Keep `POSTBUCH_DEV_AUTH_ENABLED=false` in production.
- Rotate `POSTBUCH_SECRET_KEY` and protect it as a secret.

## Suggested Hardening Additions (Not in Current Base Pattern)

- Idempotent enforcement for `oidc_subject` on upsert race conditions.
- Explicit allow/deny checks for email-null users.
- Group-to-role mapping from OIDC claim groups.
- Session expiration and idle timeout policies.
- Audit retention and alerting for role change events.

## Validation Checklist for Handoff Agent

- OIDC redirect, callback, and userinfo fetch implemented.
- User table includes `oidc_subject`, role, active flags, timestamps.
- First-login provisioning matches allowlist bootstrap behavior.
- Dev fallback login exists and is disabled in production.
- Session user loading and inactive-user eviction work.
- CSRF checks on mutating endpoints work with both forms and AJAX.
- Role-based dependencies are reusable and applied consistently.
- Tests include provisioning, updates, and fallback behavior.

## Recommended Consumption Strategy

- For exact parity: start from `reference_snapshot/`.
- For rapid transplant into a different app: start from `blueprint/`.
- For deterministic greenfield execution order: use `examples/DROP_IN_PATCH_PLAN.md`.

## Provenance

This kit was generated from the live repository implementation on `2026-03-23` and intentionally preserves real code paths and behavior.
