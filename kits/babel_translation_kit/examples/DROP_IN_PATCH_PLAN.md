# Drop-In Patch Plan: Reference Babel Translation Pattern

Apply in order.

## 1. Config and Dependencies

1. Install `Flask-Babel`.
2. Add config values:
   - `SUPPORTED_LANGUAGES`
   - `DEFAULT_LANGUAGE`
   - `BABEL_DEFAULT_LOCALE`
   - `BABEL_DEFAULT_TIMEZONE`
   - `BABEL_TRANSLATION_DIRECTORIES`
3. Ensure user model has `preferred_language` (migration if needed).

## 2. Babel App Wiring

1. Initialize `babel = Babel()` extension.
2. Add locale selector wrapper that calls `get_language()`.
3. Add timezone selector using config value.
4. Initialize in app factory via `babel.init_app(...)`.

## 3. Language Utility

1. Add `utils/language.py` (start from kit reference snapshot).
2. Preserve precedence contract:
   - admin/auth authenticated user -> `preferred_language`
   - else session -> query -> header -> default.
3. Add `set_language(lang)` helper that persists into session.

## 4. User Preference Write Paths

1. General settings route:
   - validate submitted language against `SUPPORTED_LANGUAGES`.
   - persist `current_user.preferred_language`.
2. User admin-edit route:
   - validate edited user `preferred_language` against same allowlist.
   - reject invalid input with flash + redirect.

## 5. Session Language Endpoints

1. Add `POST /set-language` for public surface.
2. Add equivalent for workspace surface if applicable.
3. Validate language against allowlist before persisting.

## 6. Translation Catalog Files

1. Add root `babel.cfg` for Python + Jinja extraction.
2. Initialize locale catalogs if first setup:
   - `pybabel init -i messages.pot -d translations -l <lang>`
3. Keep `.po` files at:
   - `translations/<lang>/LC_MESSAGES/messages.po`

## 7. Translation Pipeline

1. Add/verify scripts:
   - extract/update (`pybabel extract`, `pybabel update`)
   - compile (`pybabel compile`)
2. Optional quality steps:
   - clear fuzzy markers,
   - JSON review workflow,
   - PO validation with `msgfmt`.

## 8. Regression Tests

1. Add Babel translation test like `test_babel_translations.py`.
2. Add locale precedence test for admin/auth:
   - set user preferred `fr`, session `de`, request in admin blueprint,
   - expect `fr` locale chosen.
3. Add invalid-language persistence tests for settings endpoints.

## 9. Verification Checklist

1. Admin user changes preferred language -> backend UI language switches after next request.
2. Public `POST /set-language` changes session language.
3. `gettext/_()` values resolve from compiled `.mo` files.
4. Unsupported language submissions are rejected.
5. Celery/background contexts return default locale without request crashes.
