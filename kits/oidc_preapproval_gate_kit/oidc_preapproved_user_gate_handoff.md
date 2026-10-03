# OIDC Pre-Declared User Gate: Backend Handoff

This document defines the behavior we added on top of the original OIDC auth flow so only users explicitly created in the application can log in.

## Why This Exists
The previous pattern in `kits/authentication_kit` provisioned users on first OIDC login.
This handoff changes that behavior to a strict allow model:
- user must already exist in `users`
- user must be active
- OIDC identity is bound only after successful match

## Behavior Contract (Authoritative)
1. OIDC callback receives `sub`, `email`, and `iss` from provider claims.
2. If `sub` is missing: reject login.
3. If `email` is missing: reject login and audit deny event.
4. Normalize email to lowercase and trim spaces.
5. Lookup local user by normalized email.
6. If user does not exist: reject login and audit deny event.
7. If user exists but `is_active=false`: reject login and audit deny event.
8. If `oidc_subject` is null:
- bind `oidc_subject=sub`
- bind `oidc_issuer=iss`
- audit `oidc_bound`
9. If `oidc_subject` already set:
- require exact subject match
- if issuer is set locally and provider returns issuer, require issuer match
- reject and audit if mismatch
10. On success:
- set session user id
- ensure csrf token in session
- update `display_name` from OIDC name/preferred_username fallback
- update `last_login_at`

## Required Data Model Rules
- `users.email` must be non-null and unique.
- `users.oidc_subject` must be nullable and unique.
- `users.oidc_issuer` optional.
- Roles stay app-managed (`super_admin`, `admin`, `editor`, `viewer`).

## Admin and Bootstrap Requirements
- Add admin APIs to pre-create users and assign roles before first login.
- Add CLI bootstrap command to seed initial `super_admin` user before OIDC use.
- Keep non-production dev login fallback available.

## Audit Events To Capture
- `oidc_denied_missing_email`
- `oidc_denied_not_preapproved`
- `oidc_denied_inactive`
- `oidc_denied_subject_mismatch`
- `oidc_denied_issuer_mismatch`
- `oidc_bound`

## Session and CSRF (Unchanged)
- Session cookie auth remains in use.
- CSRF token remains required for mutating endpoints.
- `GET /api/v1/auth/me` returns authenticated user plus csrf token.

## Test Cases Required
- First login with pre-created active user binds subject and succeeds.
- Unknown email login is denied.
- Inactive user login is denied.
- Subject mismatch after binding is denied.
- Callback integration test confirms session login with mocked OIDC claims.
- RBAC and CSRF tests still pass on admin mutating routes.

## Files To Update In Existing Authentication Kit
When patching `kits/authentication_kit`, prioritize:
- `blueprint/authentication_kit/services/users.py`
- `blueprint/authentication_kit/api/routes_auth.py`
- `blueprint/tests/test_users.py`
- `README.md`
- `examples/DROP_IN_PATCH_PLAN.md`

## Non-Goals
- No auto-provision for unknown users.
- No email-domain-wide auto allow.
- No removal of dev login fallback in non-production.
