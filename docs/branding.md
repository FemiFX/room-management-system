# Branding

Everything a visitor sees that names or styles the organisation running RMS —
name, logo, colours, fonts, footer links, legal pages, email footer — comes from
`RMS_BRAND_*` settings. Templates never name an organisation themselves, so one
deployment's identity cannot leak into another's.

Re-branding is configuration only: no template edits and **no CSS rebuild**.

## Settings

| Variable | Default | Effect |
|---|---|---|
| `RMS_BRAND_NAME` | `Room Booking` | Header subtitle, copyright, email wordmark, and the organisation named in public copy ("book the rooms at …", the consent sentence) |
| `RMS_BRAND_LEGAL_NAME` | — | Header subtitle and email footer when set; falls back to the name |
| `RMS_BRAND_LOGO_URL` | — | Header logo. Absolute URL or a `/static/...` path. Empty shows no image |
| `RMS_BRAND_WEBSITE_URL` | — | "To the … website" button and portal footer link |
| `RMS_BRAND_PRIVACY_URL` | — | Footer link, and the link inside the booking form's consent sentence. Without it the sentence still reads correctly, unlinked |
| `RMS_BRAND_IMPRINT_URL` | — | Footer "Legal notice" link |
| `RMS_BRAND_CONTACT_EMAIL` / `_PHONE` | — | Footer contact block and email footer |
| `RMS_BRAND_FOOTER_LINKS` | — | Extra footer links: `Label\|https://url;Label\|https://url` |
| `RMS_BRAND_HERO_LETTERS` | — | Large rotated letters behind the public hero, cycled across six slots. Empty = no decoration |
| `RMS_BRAND_COLOR_PRIMARY` | `#3b4a6b` | Text, headings, outlines |
| `RMS_BRAND_COLOR_ACCENT` | `#f0b429` | Buttons, links, highlights |
| `RMS_BRAND_COLOR_HIGHLIGHT` | `#5b3a7a` | Secondary emphasis |
| `RMS_BRAND_COLOR_SURFACE` | `#f8fafc` | Page background of the public site and portal |
| `RMS_BRAND_COLOR_FOOTER` | `#1e293b` | Footer background |
| `RMS_BRAND_FONT_HEADING` / `_BODY` | `Inter` | Font families |
| `RMS_BRAND_FONT_CSS_URL` | — | Stylesheet that loads those fonts, if they are not already bundled |

Anything left empty renders nothing — never a placeholder or a dead link.

## How colours work

Each colour is configured as **one hex value**. `app/core/branding.py` expands
it into a 50–900 scale (tints toward white below 500, shades toward black
above) and `base.html` emits the result as CSS custom properties:

```css
:root { --c-primary: 59 74 107; --c-primary-600: 50 63 91; … }
```

The Tailwind palette (`tailwind.config.js`) maps `primary`, `accent`,
`highlight`, `surface` and `footer` to those variables, so `text-accent-600`
and `bg-primary/10` follow the configuration with opacity modifiers intact.
`main.css` carries the same defaults so the stylesheet renders on its own.

Emails are the exception: mail clients ignore CSS variables, so email
templates read literal hex values from `brand` instead.

## Example

```bash
RMS_BRAND_NAME="Example Community Centre"
RMS_BRAND_LEGAL_NAME="Example Community Centre e.V."
RMS_BRAND_LOGO_URL=https://example.org/logo.svg
RMS_BRAND_WEBSITE_URL=https://example.org
RMS_BRAND_PRIVACY_URL=https://example.org/privacy
RMS_BRAND_IMPRINT_URL=https://example.org/imprint
RMS_BRAND_CONTACT_EMAIL=rooms@example.org
RMS_BRAND_FOOTER_LINKS="Donate|https://example.org/donate;FAQ|https://example.org/faq"
RMS_BRAND_COLOR_PRIMARY=#1f3a5f
RMS_BRAND_COLOR_ACCENT=#c2410c
```

Settings are read at startup; restart the app after changing them.
