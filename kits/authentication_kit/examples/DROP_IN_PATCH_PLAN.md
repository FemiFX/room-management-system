# Drop-In Patch Plan (Greenfield Integration)

Use this plan when an AI/code agent must recreate this auth stack in a new FastAPI codebase with minimal ambiguity.

## Objective

Implement Postbuch-style authentication with:

- OIDC via Authlib
- Session cookie auth
- First-login user provisioning
- `super_admin` bootstrap via OIDC email allowlist
- Dev fallback login for non-production
- CSRF + RBAC dependencies

## Canonical Sources

1. `kits/authentication_kit/reference_snapshot/postbuch/services/users.py`
2. `kits/authentication_kit/reference_snapshot/postbuch/auth/oidc.py`
3. `kits/authentication_kit/reference_snapshot/postbuch/api/deps.py`
4. `kits/authentication_kit/reference_snapshot/postbuch/api/routes.py` (auth-specific handlers)
5. `kits/authentication_kit/reference_snapshot/tests/test_users.py`

## Patch Order (Do Not Reorder)

1. Add dependencies.
2. Add config + settings parsing.
3. Add DB base/session wiring.
4. Add core auth models (`Role`, `User`, `AuditLog`).
5. Add audit + user provisioning services.
6. Add OIDC client integration.
7. Add auth dependencies (current user, role checks, csrf).
8. Add auth routes.
9. Add login template.
10. Wire `SessionMiddleware` and router in app startup.
11. Add schema/migration for `users` and `audit_log`.
12. Add tests for provisioning behavior.

## File Creation Map

Create these files first (copy from `blueprint/` unless you need custom paths):

- `auth/oidc.py` <- `blueprint/authentication_kit/auth/oidc.py`
- `auth/deps.py` <- `blueprint/authentication_kit/api/deps.py`
- `auth/routes.py` <- `blueprint/authentication_kit/api/routes_auth.py`
- `core/config.py` <- `blueprint/authentication_kit/core/config.py`
- `core/security.py` <- `blueprint/authentication_kit/core/security.py`
- `db/base.py` <- `blueprint/authentication_kit/db/base.py`
- `db/session.py` <- `blueprint/authentication_kit/db/session.py`
- `models/enums.py` <- `blueprint/authentication_kit/models/enums.py`
- `models/user.py` <- `blueprint/authentication_kit/models/user.py`
- `models/audit_log.py` <- `blueprint/authentication_kit/models/audit_log.py`
- `services/audit.py` <- `blueprint/authentication_kit/services/audit.py`
- `services/users.py` <- `blueprint/authentication_kit/services/users.py`
- `schemas/common.py` <- `blueprint/authentication_kit/schemas/common.py`
- `schemas/user.py` <- `blueprint/authentication_kit/schemas/user.py`
- `templates/auth/login.html` <- `blueprint/authentication_kit/templates/auth/login.html`

If needed, use SQL baseline from:

- `examples/users_and_audit_schema.sql`

## Mandatory Runtime Wiring

In app startup (`main.py` equivalent):

1. Add `SessionMiddleware`.
2. Use `secret_key` from env settings.
3. Set `session_cookie` from settings.
4. Include auth router.
5. Ensure Jinja template loader can resolve `templates/auth/login.html`.

Reference minimal implementation:

- `blueprint/examples/main.py`

## Required Env Vars

At minimum:

- `POSTBUCH_SECRET_KEY`
- `POSTBUCH_SESSION_COOKIE_NAME`
- `POSTBUCH_OIDC_ENABLED`
- `POSTBUCH_OIDC_SERVER_METADATA_URL`
- `POSTBUCH_OIDC_CLIENT_ID`
- `POSTBUCH_OIDC_CLIENT_SECRET`
- `POSTBUCH_OIDC_SCOPES`
- `POSTBUCH_OIDC_ADMIN_EMAILS`
- `POSTBUCH_DEV_AUTH_ENABLED`
- `POSTBUCH_ENV`

See:

- `blueprint/.env.example`

## Acceptance Criteria

1. `GET /auth/login` redirects to OIDC when enabled and dev fallback is off.
2. `GET /auth/callback` provisions/updates user by `oidc_subject`.
3. First allowlisted email is created as `super_admin`.
4. First non-allowlisted email is created as `viewer`.
5. `POST /auth/dev-login` returns 404 in production.
6. `get_current_user` clears invalid/inactive sessions.
7. Mutating routes reject requests without valid CSRF token.
8. `/api/me` returns authenticated user.

## Test Sequence

1. Add the three provisioning tests from `blueprint/tests/test_users.py`.
2. Run tests.
3. Validate an end-to-end manual login once with OIDC sandbox/tenant.

## Common Integration Pitfalls

- Forgetting `SessionMiddleware` before route handling.
- Missing `python-multipart` (breaks form parsing for dev login).
- Keeping `https_only=False` in production.
- Not setting `POSTBUCH_OIDC_ADMIN_EMAILS`, causing no bootstrap admin.
- Copying full app `User` model relationships that depend on non-auth models.

