# Babel Translation Kit (Reference Pattern: User Preference + Session Locale)

> **Note on `reference_snapshot/`**
>
> Some kits originally shipped a `reference_snapshot/` directory holding verbatim
> copies of the upstream files the kit was extracted from. Those snapshots are not
> part of this public release — they contained source from unrelated private
> projects. Paths of the form `reference_snapshot/...` referenced below describe the
> original layout and are not present in this repository.


This kit captures the exact i18n pattern used in this repository for Flask-Babel-based UI translation.

It focuses on two things:
- how translations are extracted, updated, and compiled with Babel, and
- how `User.preferred_language` controls which language the reference backend is rendered in.

## Goal

Provide a reusable, implementation-level i18n baseline for a Flask app with mixed surfaces:
- admin/auth UI language controlled by authenticated user preference,
- public/workspace language controlled by session/query/browser,
- Babel catalogs for template + Python message strings,
- deterministic translation maintenance pipeline.

## What Is Included

1. `reference_snapshot/`
Direct source copies from this repo for core behavior:
- `backend/app/utils/language.py`
- `backend/tests/test_babel_translations.py`

2. `examples/`
Implementation docs for fast transplant:
- `BACKEND_INTEGRATION_EXAMPLES.md`
- `DROP_IN_PATCH_PLAN.md`

## Directory Layout

```text
kits/babel_translation_kit/
  README.md
  examples/
    BACKEND_INTEGRATION_EXAMPLES.md
    DROP_IN_PATCH_PLAN.md
  reference_snapshot/
    ORIGIN.md
    backend/
      app/utils/language.py
      tests/test_babel_translations.py
```

## Behavior Contract (Exact Reference Pattern)

### 1. Babel Wiring

Babel is initialized in `create_app` with selectors:
- locale selector: `_select_locale -> get_language()`
- timezone selector: `_select_timezone -> Config.BABEL_DEFAULT_TIMEZONE`

Source of truth:
- `backend/app/__init__.py`

### 2. Locale Resolution Priority

In `backend/app/utils/language.py`, `get_language()` follows this logic:

- No request context (e.g., Celery): return `DEFAULT_LANGUAGE`
- For `admin` and `auth` blueprints with authenticated user:
  - use `current_user.preferred_language` if supported
  - otherwise fallback to `DEFAULT_LANGUAGE`
- For all other surfaces:
  - `session["language"]` (if valid)
  - query param `?lang=` (if valid; persisted to session)
  - `Accept-Language` header best match (persisted to session)
  - fallback `DEFAULT_LANGUAGE` (persisted to session)

This is the key pattern in this repository.

### 3. How `preferred_language` Defines Backend UI Language

`User.preferred_language` is stored on the user record (`backend/app/models/user.py`) and is used by locale selection for admin/auth.

Practical effect:
- once a user is logged in on backend/auth pages, backend text translated with `_()` is rendered in that user’s `preferred_language`.
- this bypasses session/query/header precedence specifically for admin/auth surfaces.

Current update entry points:
- `/admin/settings/general` (`settings_general_page`): validates submitted language against `Config.SUPPORTED_LANGUAGES` before saving.
- `/admin/users/<id>/update` (`users_update`): allows super-admin editing of another user’s `preferred_language`.

Important consistency note:
- The settings route validates language membership.
- The user-edit route currently writes posted value directly; hardening should add the same allowlist validation.

### 4. Public/Workspace Language Model

Public/workspace language is session-centric and switchable via API endpoints:
- `POST /set-language` on public blueprint
- `POST /set-language` on workspace blueprint

Both store selected language in session (`set_language`), then subsequent requests use that session locale.

### 5. Config Contract

From `backend/app/config.py`:
- `SUPPORTED_LANGUAGES = ["en", "de", "fr", "pt", "es", "yo", "sw"]`
- `DEFAULT_LANGUAGE = "de"`
- `BABEL_DEFAULT_LOCALE = DEFAULT_LANGUAGE`
- `BABEL_DEFAULT_TIMEZONE` (env, default `UTC`)
- `BABEL_TRANSLATION_DIRECTORIES` (env, default `<repo>/translations`)

## Translation Catalog Workflow (Babel)

Repository pattern:

1. Extract message keys:
```bash
pybabel extract -F babel.cfg -o messages.pot backend
```

2. Update `.po` files under `translations/<lang>/LC_MESSAGES/messages.po`:
```bash
pybabel update -i messages.pot -d translations
```

3. Compile `.mo` files:
```bash
pybabel compile -d translations
```

Automated pipeline script:
- `scripts/run_translation_pipeline.sh`
  - extract/update
  - zero fuzzy
  - update translations
  - compile

Extraction config:
- root `babel.cfg`
  - `[python: **.py]`
  - `[jinja2: **/templates/**.html]`

## Template and Code Usage Contract

Use `_()` for user-facing strings in:
- Python flashes/responses
- Jinja templates

Examples from repo:
- `backend/app/views/auth.py` (`flash(_("..."))`)
- admin/public/workspace templates with `{{ _('...') }}`

## Minimal Integration Checklist

1. Add Babel extension and initialize with locale/timezone selectors.
2. Implement `get_language()` with the documented precedence (admin/auth user preference override).
3. Add `preferred_language` column on `User` and ensure write paths.
4. Define `SUPPORTED_LANGUAGES`, `DEFAULT_LANGUAGE`, and translation directory.
5. Add `/set-language` endpoint for session-backed surfaces.
6. Maintain `translations/<lang>/LC_MESSAGES/messages.po` and compiled `.mo` files.
7. Add tests that assert translation output under request contexts.

## Testing Pattern

Reference test file:
- `reference_snapshot/backend/tests/test_babel_translations.py`

Test strategy:
- create app with absolute `BABEL_TRANSLATION_DIRECTORIES`
- open request context with `?lang=<code>`
- force locale selector (`get_language()`)
- assert `gettext(source) == expected`

## Hardening Recommendations

1. Validate `preferred_language` everywhere it can be persisted (especially `/admin/users/<id>/update`).
2. Keep language option rendering in templates driven by `SUPPORTED_LANGUAGES` instead of hardcoded subsets.
3. Add regression tests for admin/auth preference precedence:
   - authenticated admin user with `preferred_language=fr` should get French even if session/header says otherwise.
4. Add telemetry for rejected/unsupported language submissions.

## Provenance

Pattern captured from live repository implementation on 2026-04-10.
