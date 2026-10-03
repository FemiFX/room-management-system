# Drop-In Patch Plan: File Viewer Kit

1. Copy templates
- Copy `templates/public/partials/media_file_viewer.html`.
- If needed for legacy pathing, copy `templates/backend/partials/file_viewer.html`.

2. Ensure URL helper
- Expose `storage_url(object_key)` in Jinja globals/context.

3. Wire context
- Pass a `media` object with `object_key` and optional `file_size`, `mime_type`.

4. Add helper (optional)
- Copy `backend/file_viewer_context.py` and use `build_media_file_context(media)` for normalized metadata.

5. Integrate in page template
- Include partial where publication/media file should render.

6. Verify front-end behavior
- Test image, PDF, DOCX, and unsupported extension scenarios.
