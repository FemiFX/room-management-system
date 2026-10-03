"""Deployment branding, resolved once from settings for templates and email.

Templates read ``brand.*`` and never name an organisation themselves. Colours
are configured as one hex value each and expanded here into the 50-900 scales
the stylesheet uses, emitted as CSS custom properties -- so changing the brand
is a configuration change, not a CSS rebuild.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from app.core.config import get_settings

#: Mix ratios for the generated scale. Below 500 mixes toward white, above it
#: toward black; 500 is the configured colour itself.
_TINTS = {50: 0.95, 100: 0.86, 200: 0.70, 300: 0.50, 400: 0.25}
_SHADES = {600: 0.15, 700: 0.30, 800: 0.45, 900: 0.60}
_SCALES = ("primary", "accent", "highlight")


def _hex_to_rgb(value: str) -> tuple[int, int, int]:
    raw = (value or "").strip().lstrip("#")
    if len(raw) == 3:
        raw = "".join(ch * 2 for ch in raw)
    if len(raw) != 6:
        raise ValueError(f"not a hex colour: {value!r}")
    return int(raw[0:2], 16), int(raw[2:4], 16), int(raw[4:6], 16)


def _mix(rgb: tuple[int, int, int], target: int, ratio: float) -> tuple[int, int, int]:
    return tuple(round(c + (target - c) * ratio) for c in rgb)  # type: ignore[return-value]


def _channels(rgb: tuple[int, int, int]) -> str:
    return f"{rgb[0]} {rgb[1]} {rgb[2]}"


def build_scale(hex_value: str) -> dict[str, str]:
    """Return {"DEFAULT"|"50".."900": "r g b"} for one base colour."""
    base = _hex_to_rgb(hex_value)
    scale = {"DEFAULT": _channels(base), "500": _channels(base)}
    for step, ratio in _TINTS.items():
        scale[str(step)] = _channels(_mix(base, 255, ratio))
    for step, ratio in _SHADES.items():
        scale[str(step)] = _channels(_mix(base, 0, ratio))
    return scale


def _parse_links(raw: str) -> list[tuple[str, str]]:
    links = []
    for chunk in (raw or "").split(";"):
        if "|" not in chunk:
            continue
        label, _, url = chunk.partition("|")
        if label.strip() and url.strip():
            links.append((label.strip(), url.strip()))
    return links


@dataclass(frozen=True)
class Branding:
    name: str
    legal_name: str
    logo_url: str
    website_url: str
    privacy_url: str
    imprint_url: str
    contact_email: str
    contact_phone: str
    footer_links: list[tuple[str, str]] = field(default_factory=list)
    hero_letters: list[str] = field(default_factory=list)
    primary_hex: str = ""
    accent_hex: str = ""
    surface_hex: str = ""
    #: "r,g,b" of the primary colour, for rgba() in email inline styles --
    #: mail clients do not support CSS variables.
    primary_rgb: str = ""
    css_variables: str = ""
    font_css_url: str = ""

    @property
    def email_footer_line(self) -> str:
        parts = [self.legal_name or self.name, self.contact_phone, self.contact_email]
        return " · ".join(p for p in parts if p)


_cache: tuple[object, "Branding"] | None = None


def get_branding() -> Branding:
    """Branding for the current settings object.

    Cached against the settings instance itself rather than with its own
    lru_cache, so anything that refreshes settings (tests clearing
    get_settings' cache) gets fresh branding without a second reset to know
    about.
    """
    global _cache
    s = get_settings()
    if _cache is not None and _cache[0] is s:
        return _cache[1]
    branding = _build(s)
    _cache = (s, branding)
    return branding


def _build(s) -> Branding:
    lines = []
    for name, hex_value in (
        ("primary", s.brand_color_primary),
        ("accent", s.brand_color_accent),
        ("highlight", s.brand_color_highlight),
    ):
        for step, channels in build_scale(hex_value).items():
            suffix = "" if step == "DEFAULT" else f"-{step}"
            lines.append(f"--c-{name}{suffix}: {channels};")
    lines.append(f"--c-surface: {_channels(_hex_to_rgb(s.brand_color_surface))};")
    lines.append(f"--c-footer: {_channels(_hex_to_rgb(s.brand_color_footer))};")
    lines.append(f"--font-heading: '{s.brand_font_heading}', ui-sans-serif, system-ui, sans-serif;")
    lines.append(f"--font-body: '{s.brand_font_body}', ui-sans-serif, system-ui, sans-serif;")

    return Branding(
        name=s.brand_name,
        legal_name=s.brand_legal_name,
        logo_url=s.brand_logo_url,
        website_url=s.brand_website_url,
        privacy_url=s.brand_privacy_url,
        imprint_url=s.brand_imprint_url,
        contact_email=s.brand_contact_email,
        contact_phone=s.brand_contact_phone,
        footer_links=_parse_links(s.brand_footer_links),
        hero_letters=[ch for ch in s.brand_hero_letters if not ch.isspace()],
        primary_hex="#" + s.brand_color_primary.strip().lstrip("#"),
        accent_hex="#" + s.brand_color_accent.strip().lstrip("#"),
        surface_hex="#" + s.brand_color_surface.strip().lstrip("#"),
        primary_rgb=",".join(str(c) for c in _hex_to_rgb(s.brand_color_primary)),
        css_variables=":root{" + "".join(lines) + "}",
        font_css_url=s.brand_font_css_url,
    )
