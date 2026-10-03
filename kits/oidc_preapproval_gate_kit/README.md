# OIDC Preapproval Gate Kit

> **Note on `reference_snapshot/`**
>
> Some kits originally shipped a `reference_snapshot/` directory holding verbatim
> copies of the upstream files the kit was extracted from. Those snapshots are not
> part of this public release — they contained source from unrelated private
> projects. Paths of the form `reference_snapshot/...` referenced below describe the
> original layout and are not present in this repository.


This kit captures the strict OIDC preapproval behavior where only users explicitly created in-app can log in.

## Goal
Patch an existing OIDC/session auth stack (especially `kits/authentication_kit`) from auto-provision-on-login to pre-declared-user-only login.

## Includes
- `examples/DROP_IN_PATCH_PLAN.md`: deterministic implementation order.
- `examples/BEHAVIOR_CONTRACT.md`: exact login gate contract.
- `reference_snapshot/`: concrete implementation references from this repo backend.

## Main Behavior Delta vs Original Authentication Kit
Original behavior:
- first OIDC login creates local user automatically.

New behavior:
- user must already exist and be active.
- first successful login only binds OIDC subject and issuer.
- unknown or inactive users are denied.

## Patch Targets in Existing Kit
- `kits/authentication_kit/blueprint/authentication_kit/services/users.py`
- `kits/authentication_kit/blueprint/authentication_kit/api/routes_auth.py`
- `kits/authentication_kit/blueprint/tests/test_users.py`
- `kits/authentication_kit/README.md`

## Provenance
Generated from implementation in this repository on 2026-03-23.
