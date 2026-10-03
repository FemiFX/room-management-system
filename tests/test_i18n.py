from __future__ import annotations

import re

from sqlalchemy import select

from app.models.user import User


def _extract_html_lang(html: str) -> str:
    match = re.search(r'<html[^>]*lang="([^"]+)"', html)
    assert match is not None
    return match.group(1)


def test_login_accept_language_sets_locale(client):
    response = client.get("/auth/login", headers={"Accept-Language": "fr-FR,fr;q=0.9,en;q=0.8"})
    assert response.status_code == 200
    assert _extract_html_lang(response.text) == "fr"


def test_login_query_language_persists_to_session(client):
    response = client.get("/auth/login?lang=en")
    assert response.status_code == 200
    assert _extract_html_lang(response.text) == "en"

    follow_up = client.get("/auth/login")
    assert follow_up.status_code == 200
    assert _extract_html_lang(follow_up.text) == "en"


def test_admin_uses_user_preferred_language_over_session(client, db_session, dev_login):
    csrf = dev_login(email="language.admin@example.com", display_name="Language Admin")
    # set-language is a mutation and now requires CSRF like every other one.
    language_res = client.post(
        "/api/v1/set-language", json={"language": "de"}, headers={"x-csrf-token": csrf}
    )
    assert language_res.status_code == 200
    assert language_res.json()["language"] == "de"

    user = db_session.scalar(select(User).where(User.email == "language.admin@example.com"))
    assert user is not None
    user.preferred_language = "fr"
    db_session.commit()

    dashboard = client.get("/dashboard", headers={"x-csrf-token": csrf})
    assert dashboard.status_code == 200
    assert _extract_html_lang(dashboard.text) == "fr"


def test_set_language_requires_csrf(client, dev_login):
    """It was the one unauthenticated mutating endpoint in the app."""
    dev_login(email="csrf.admin@example.com", display_name="CSRF Admin")
    assert client.post("/api/v1/set-language", json={"language": "de"}).status_code == 400


def test_explicit_lang_query_beats_a_remembered_session_language(client):
    """A link-based switcher is useless if the stored value always wins."""
    assert _extract_html_lang(client.get("/auth/login?lang=en").text) == "en"
    assert _extract_html_lang(client.get("/auth/login?lang=de").text) == "de"
    # And with no query it falls back to what was last chosen.
    assert _extract_html_lang(client.get("/auth/login").text) == "de"


def test_public_page_language_switcher_works_without_javascript(client):
    """The public switcher is plain links, so it must work on a bare GET."""
    assert _extract_html_lang(client.get("/book?lang=en").text) == "en"
    assert _extract_html_lang(client.get("/book?lang=de").text) == "de"
