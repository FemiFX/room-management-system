# Drop-In Patch Plan: OIDC Pre-Declared User Gate

## Objective
Replace first-login auto provisioning with strict pre-approved-user login.

## Patch Order
1. Update user provisioning service.
2. Update OIDC callback route.
3. Add or update audit event paths.
4. Update tests for allow and deny flows.
5. Update kit documentation and handoff docs.

## Service-Level Changes
- Remove fallback creation for unknown OIDC users.
- Add email normalization before lookup.
- Enforce `user exists` and `user.is_active`.
- Add bind-on-first-success (`oidc_subject`, `oidc_issuer`).
- Add mismatch checks for subject and issuer.

## Route-Level Changes
- Callback must call new preapproval gate service.
- Return 403 on gate failure with clear detail.
- Preserve session and csrf token behavior on success.

## Test Changes
- Add tests:
- pre-created active user can login and bind subject
- unknown user denied
- inactive user denied
- bound subject mismatch denied

## Docs Changes
- Document behavior delta from original auto-provision pattern.
- Document required schema assumptions for `users` table.
