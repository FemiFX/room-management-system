"""Storing a document against a booking.

The liability certificate can arrive by three different doors -- the public
form at submit time, the manage link days later, or staff uploading what
turned up in their inbox -- and all three must agree on what is acceptable and
what happens to the file that is already there. That agreement lives here
rather than being written out three times.
"""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.booking import Booking
from app.models.document import Document
from app.models.enums import DocumentType
from app.services.audit import audit
from app.storage.minio_client import delete_object, upload_bytes


class DocumentRejected(ValueError):
    """The file cannot be stored.

    Carries a `code` rather than only a sentence: the caller has the request,
    and therefore the language. Passing str(exc) to gettext would look up a
    msgid assembled at runtime, which is never extracted and always falls
    through to English.
    """

    def __init__(self, message: str, *, code: str) -> None:
        super().__init__(message)
        self.code = code


#: Formats an office can actually open. A certificate is a scan or a PDF;
#: anything else is a mistake, and accepting it only defers the problem.
ALLOWED_TYPES = {
    "application/pdf": "pdf",
    "image/jpeg": "jpg",
    "image/png": "png",
    "image/webp": "webp",
    "image/heic": "heic",
}

#: A phone photo of a certificate is comfortably under this.
MAX_BYTES = 10 * 1024 * 1024


def describe_limits() -> tuple[str, int]:
    return "PDF, JPG, PNG", MAX_BYTES // (1024 * 1024)


def find_certificate(db: Session, booking_id: int) -> Document | None:
    return db.scalar(
        select(Document)
        .where(
            Document.booking_id == booking_id,
            Document.document_type == DocumentType.INSURANCE,
        )
        .order_by(Document.uploaded_at.desc())
    )


def store_certificate(
    db: Session,
    booking: Booking,
    *,
    filename: str | None,
    content_type: str | None,
    blob: bytes,
    uploaded_by_user_id: int | None = None,
    title: str | None = None,
) -> Document:
    """Attach a liability certificate to a booking, replacing any earlier one.

    Replaces rather than accumulates: there is one current certificate for a
    booking, and a list of three near-identical PDFs helps nobody decide
    whether the cover is in order. The superseded object is removed from
    storage only after the row is committed, so a failed commit cannot leave a
    document row pointing at a file that is gone.
    """
    suffix = ALLOWED_TYPES.get((content_type or "").lower())
    if suffix is None:
        raise DocumentRejected("Unsupported file type.", code="type")
    if not blob:
        raise DocumentRejected("Empty file.", code="empty")
    if len(blob) > MAX_BYTES:
        raise DocumentRejected("File too large.", code="too_large")

    previous = find_certificate(db, booking.id)

    # The submitted filename is kept as a label but never used to build the
    # key: it is attacker-controlled text, and object storage should not be
    # asked to be careful with it.
    object_key = f"documents/insurance/{booking.id}/{uuid4().hex}.{suffix}"
    upload_bytes(object_key=object_key, data=blob, content_type=content_type)

    row = Document(
        booking_id=booking.id,
        room_id=booking.room_id,
        uploaded_by_user_id=uploaded_by_user_id,
        document_type=DocumentType.INSURANCE,
        title=title or "Liability insurance certificate",
        object_key=object_key,
        original_filename=(filename or "")[:255] or None,
        mime_type=content_type,
        file_size=len(blob),
        uploaded_at=datetime.now(timezone.utc),
    )
    db.add(row)
    if previous is not None:
        db.delete(previous)
    db.flush()

    audit(
        db,
        entity=row,
        action="uploaded",
        actor_user_id=uploaded_by_user_id,
        after={
            "booking_id": booking.id,
            "document_type": DocumentType.INSURANCE.value,
            "original_filename": row.original_filename,
            "file_size": row.file_size,
        },
    )
    db.commit()

    if previous is not None:
        try:
            delete_object(object_key=previous.object_key)
        except Exception:
            # The row is already gone; an orphaned object is tidy-up, not a
            # failure the uploader should hear about.
            pass

    db.refresh(row)
    return row
