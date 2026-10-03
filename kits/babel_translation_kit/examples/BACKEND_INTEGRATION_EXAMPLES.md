# Backend Integration Examples (Reference Babel Pattern)

## 1) App Factory Babel Initialization

```python
from flask import Flask
from flask_babel import Babel

babel = Babel()


def _select_locale():
    from app.utils.language import get_language
    return get_language()


def _select_timezone():
    from app.config import Config
    return Config.BABEL_DEFAULT_TIMEZONE


def create_app(config_class):
    app = Flask(__name__)
    app.config.from_object(config_class)

    babel.init_app(
        app,
        locale_selector=_select_locale,
        timezone_selector=_select_timezone,
    )

    return app
```

## 2) Locale Resolver With Admin/Auth Preference Override

```python
from flask import current_app, has_request_context, request, session
from flask_login import current_user


def get_language() -> str:
    supported = current_app.config.get("SUPPORTED_LANGUAGES", ["de"])
    default = current_app.config.get("DEFAULT_LANGUAGE", "de")

    if not has_request_context():
        return default

    # the reference backend rule: authenticated admin/auth users use DB preference.
    if request.blueprint in ("admin", "auth") and current_user.is_authenticated:
        preferred = getattr(current_user, "preferred_language", None)
        if preferred in supported:
            return preferred
        return default

    if session.get("language") in supported:
        return session["language"]

    query_lang = request.args.get("lang")
    if query_lang in supported:
        session["language"] = query_lang
        return query_lang

    best = request.accept_languages.best_match(supported)
    if best:
        session["language"] = best
        return best

    session["language"] = default
    return default
```

## 3) Persist Preferred Language in User Settings

```python
@admin_bp.route("/settings/general", methods=["GET", "POST"])
@login_required
def settings_general_page():
    supported_languages = Config.SUPPORTED_LANGUAGES

    if request.method == "POST":
        preferred_language = request.form.get("preferred_language", "").strip()
        if preferred_language not in supported_languages:
            flash(_("Ungültige Sprache ausgewählt."), "error")
            return redirect(url_for("admin.settings_general_page"))

        current_user.preferred_language = preferred_language
        db.session.commit()
        flash(_("Einstellungen gespeichert."), "success")
        return redirect(url_for("admin.settings_general_page"))

    return render_template(
        "admin/settings_general.html",
        supported_languages=supported_languages,
    )
```

## 4) Language Switch Endpoint (Session-Backed)

```python
@public_bp.route("/set-language", methods=["POST"])
def set_user_language():
    data = request.get_json(silent=True) or {}
    lang = (data.get("language") or "").strip().lower()

    if lang not in current_app.config.get("SUPPORTED_LANGUAGES", []):
        return jsonify({"error": _("Ungültiger Sprachcode")}), 400

    session["language"] = lang
    session.modified = True
    return jsonify({"language": lang}), 200
```

## 5) Babel CLI Workflow

```bash
# 1) Extract strings
pybabel extract -F babel.cfg -o messages.pot backend

# 2) Update locale catalogs
pybabel update -i messages.pot -d translations

# 3) Compile runtime catalogs
pybabel compile -d translations
```

## 6) Babel Config

```ini
[python: **.py]
[jinja2: **/templates/**.html]
extensions=jinja2.ext.do,jinja2.ext.loopcontrols
```

## 7) Regression Test Pattern

```python
with app.test_request_context("/?lang=fr"):
    get_language()
    assert gettext("Entdecken Sie die") == "Découvrez la"
```

Add one more test for backend precedence:
- authenticated admin user with `preferred_language = "fr"`
- session language set to `"de"`
- assert effective locale resolves to `"fr"`
