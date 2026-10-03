"""Branding comes from settings, never from templates.

Pins three things: the colour-scale maths, that an unconfigured deployment
renders no organisation-specific links (and no dead ones), and that configured
values actually reach the page.
"""

from __future__ import annotations

import re
from pathlib import Path

from fastapi.testclient import TestClient

from app import create_app
from app.core.branding import build_scale, get_branding
from app.core.config import get_settings

TEMPLATES = Path(__file__).resolve().parents[1] / "app" / "templates"


def _channels(value: str) -> tuple[int, ...]:
    return tuple(int(c) for c in value.split())


def test_scale_has_every_step_and_runs_light_to_dark():
    scale = build_scale("#3b4a6b")
    assert set(scale) == {"DEFAULT", "50", "100", "200", "300", "400", "500", "600", "700", "800", "900"}
    assert scale["DEFAULT"] == scale["500"] == "59 74 107"
    brightness = [sum(_channels(scale[str(step)])) for step in (50, 100, 200, 300, 400, 500, 600, 700, 800, 900)]
    assert brightness == sorted(brightness, reverse=True), "scale must darken monotonically"


def test_short_hex_is_accepted():
    assert build_scale("#fff")["DEFAULT"] == "255 255 255"


def test_unconfigured_public_page_has_no_dead_links(client):
    html = client.get("/book").text
    assert 'href=""' not in html
    assert "Room Booking" in html
    # With no logo configured, no <img> points at a missing file.
    assert "img/" not in html


def test_configured_branding_reaches_the_page(db_setup, monkeypatch):
    monkeypatch.setenv("RMS_BRAND_NAME", "Example Community Centre")
    monkeypatch.setenv("RMS_BRAND_WEBSITE_URL", "https://example.org")
    monkeypatch.setenv("RMS_BRAND_PRIVACY_URL", "https://example.org/privacy")
    monkeypatch.setenv("RMS_BRAND_LOGO_URL", "https://example.org/logo.svg")
    monkeypatch.setenv("RMS_BRAND_FOOTER_LINKS", "Donate|https://example.org/donate")
    monkeypatch.setenv("RMS_BRAND_COLOR_PRIMARY", "#102030")
    get_settings.cache_clear()

    with TestClient(create_app()) as client:
        html = client.get("/book").text

    assert "Example Community Centre" in html
    assert 'href="https://example.org"' in html
    assert 'href="https://example.org/privacy"' in html
    assert 'src="https://example.org/logo.svg"' in html
    assert ">Donate<" in html
    assert "--c-primary: 16 32 48;" in html


def test_footer_links_parse_and_skip_malformed_entries(db_setup, monkeypatch):
    monkeypatch.setenv("RMS_BRAND_FOOTER_LINKS", "A|https://a.example;broken;B|https://b.example;|nolabel")
    get_settings.cache_clear()
    assert get_branding().footer_links == [("A", "https://a.example"), ("B", "https://b.example")]


def test_no_template_hardcodes_a_colour_from_the_brand_palette():
    """Brand colours must come from variables. A literal hex in a public,
    portal or email template is a colour that ignores configuration."""
    offenders = []
    for path in list(TEMPLATES.glob("public/**/*.html")) + list(TEMPLATES.glob("portal/**/*.html")) + list(
        TEMPLATES.glob("email/**/*.html")
    ):
        for line_no, line in enumerate(path.read_text().splitlines(), 1):
            for match in re.findall(r"#[0-9a-fA-F]{6}\b", line):
                if match.lower() not in {"#ffffff", "#000000"}:
                    offenders.append(f"{path.relative_to(TEMPLATES)}:{line_no} {match}")
    assert not offenders, "hardcoded colours:\n" + "\n".join(offenders)
