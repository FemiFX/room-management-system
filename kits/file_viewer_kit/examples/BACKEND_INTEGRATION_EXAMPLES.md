# Backend Integration Examples (Current Style)

## 1) Build content payload with media object

```python
# backend/app/views/public.py (_get_content_data excerpt)
media_content = MediaContent.query.filter_by(content_id=content.id).first()

content_data = {
    "id": content.id,
    "type": content.type,
    "title": translation.title,
    ...
    "media_content": media_content,
}
```

## 2) Render publication page with media data

```python
# backend/app/views/public.py (publication_detail excerpt)
return render_template(
    "public/content_publication.html",
    current_language=current_language,
    current_year=datetime.now().year,
    content=content_data,
    available_languages=available_languages,
    related_results=related,
    related_media=related_media,
)
```

## 3) Template include pattern

```jinja
{% set media = content.media_content %}
{% include "public/partials/media_file_viewer.html" %}
```

## 4) Admin-side payload pattern (if using dict payloads)

```python
# backend/app/views/routes.py (view_publication excerpt)
publication_data = {
    "object_key": media.object_key if media else None,
    "mime_type": media.mime_type if media else None,
    "file_size_mb": round(media.file_size / (1024 * 1024), 2) if media and media.file_size else None,
}
```

## 5) Optional context normalizer helper

```python
from file_viewer_context import build_media_file_context
viewer_context = build_media_file_context(media)
```
