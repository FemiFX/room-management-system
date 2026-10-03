# Behavior Contract: OIDC Preapproval Gate

## Inputs
- OIDC claims: `sub`, `email`, optional `iss`, optional `name/preferred_username`.

## Preconditions
- User must be explicitly created in local `users` table.
- User email must be normalized before lookup.

## Decision Logic
1. If `sub` missing: reject.
2. If `email` missing: reject.
3. If no local user by email: reject.
4. If local user inactive: reject.
5. If local `oidc_subject` null: set it from `sub`, set issuer, allow.
6. Else require exact subject match.
7. If issuer exists locally and in claim, require exact issuer match.

## Post-Success Effects
- `session.user_id` set.
- csrf token ensured.
- `display_name` refreshed from claims.
- `last_login_at` updated.

## Audit Events
- denied_missing_email
- denied_not_preapproved
- denied_inactive
- denied_subject_mismatch
- denied_issuer_mismatch
- oidc_bound
