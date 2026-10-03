# File Viewer Kit (MediaContent / Publication Flow)

> **Note on `reference_snapshot/`**
>
> Some kits originally shipped a `reference_snapshot/` directory holding verbatim
> copies of the upstream files the kit was extracted from. Those snapshots are not
> part of this public release — they contained source from unrelated private
> projects. Paths of the form `reference_snapshot/...` referenced below describe the
> original layout and are not present in this repository.


This kit is aligned with the current codebase file-viewing behavior for publication/media files.

## Goal

Provide a reusable file-viewer baseline that matches current templates and data model:
- preview for images and PDFs,
- DOCX/DOC modal rendering via Mammoth,
- full-screen modal fallback for supported formats,
- direct download link via storage URL.

## What Is Included

This kit has two layers:

1. `reference_snapshot/`
Direct source copies/excerpts from the current repository.

2. portable kit files at root
Trimmed artifacts for fast transplant into another repo.

Root kit files:
- `templates/public/partials/media_file_viewer.html`
  - Current-style file viewer partial built around `MediaContent.object_key` + `storage_url(...)`.
- `templates/backend/partials/file_viewer.html`
  - Compatibility mirror of the same partial for older include paths.
- `backend/file_viewer_context.py`
  - Helper for preparing viewer context from a MediaContent-like object.
- `examples/DROP_IN_PATCH_PLAN.md`
  - Step-by-step integration sequence.
- `examples/BACKEND_INTEGRATION_EXAMPLES.md`
  - Backend wiring examples from the current codebase.

Reference snapshot files:
- `reference_snapshot/backend/app/templates/public/content_detail.html`
- `reference_snapshot/backend/app/templates/public/content_publication.html`
- `reference_snapshot/backend/app/views/public_file_viewer_excerpt.py`
- `reference_snapshot/ORIGIN.md`

## Current Reality (Important)

The older `Document + scan_status` flow is no longer present in the active app code.
Current templates use `MediaContent` records and `storage_url(media.object_key)`.

## Template Context Contract

Required:
- `media` object with:
  - `object_key`
  - optional `file_size`
  - optional `mime_type`
- `storage_url` template helper

Optional:
- `title`

## Integration Example (Jinja)

```jinja
{% set media = content.media_content %}
{% include "public/partials/media_file_viewer.html" %}
```

## Integration Notes

- The partial computes filename/ext from `media.object_key`.
- PDF preview uses `<embed>` and offers open-in-tab/fullscreen actions.
- DOCX/DOC preview uses Mammoth CDN at runtime.
- Unsupported formats fall back to extension-aware placeholder + download action.

## Provenance

Updated from live repository templates on 2026-03-23.
