"""Helpers for preparing file-viewer template context from MediaContent-like rows."""


def build_media_file_context(media):
    """
    Convert a MediaContent-like object into viewer-friendly metadata.

    Expected media attributes:
    - object_key
    - file_size (bytes, optional)
    - mime_type (optional)
    """
    if not media or not getattr(media, "object_key", None):
        return None

    object_key = media.object_key
    filename = object_key.split("/")[-1]
    file_ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    file_size = getattr(media, "file_size", None) or 0

    return {
        "object_key": object_key,
        "filename": filename,
        "file_ext": file_ext,
        "file_size_bytes": file_size,
        "file_size_mb": round(file_size / (1024 * 1024), 2) if file_size else 0,
        "mime_type": getattr(media, "mime_type", None),
    }
