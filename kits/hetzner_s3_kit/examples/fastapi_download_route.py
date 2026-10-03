from __future__ import annotations

from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import RedirectResponse

from hetzner_s3_client import build_client, load_settings

app = FastAPI()


class StoredFile:
    """Replace this with your SQLAlchemy model."""

    def __init__(self, storage_key: str, original_filename: str, mime_type: str):
        self.storage_key = storage_key
        self.original_filename = original_filename
        self.mime_type = mime_type


def get_current_user():
    """Placeholder for your app's auth dependency."""
    return object()


def get_file_from_database(file_id: int) -> StoredFile | None:
    """Replace this with a real database lookup."""
    if file_id != 1:
        return None
    return StoredFile(
        storage_key="uploads/2026/04/example.pdf",
        original_filename="example.pdf",
        mime_type="application/pdf",
    )


@app.get("/files/{file_id}/download")
def download_file(file_id: int, _current_user=Depends(get_current_user)):
    stored = get_file_from_database(file_id)
    if stored is None:
        raise HTTPException(status_code=404)

    settings = load_settings()
    client = build_client(settings)
    safe_filename = stored.original_filename.replace('"', "_").replace("\n", "_").replace("\r", "_")
    url = client.generate_presigned_url(
        "get_object",
        Params={
            "Bucket": settings.bucket,
            "Key": stored.storage_key,
            "ResponseContentDisposition": f'attachment; filename="{safe_filename}"',
            "ResponseContentType": stored.mime_type,
        },
        ExpiresIn=settings.presigned_url_ttl_seconds,
    )
    return RedirectResponse(url, status_code=307)

