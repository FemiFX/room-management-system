from enum import StrEnum


class Role(StrEnum):
    SUPER_ADMIN = "super_admin"
    ADMIN = "admin"
    EDITOR = "editor"
    VIEWER = "viewer"


class Direction(StrEnum):
    INCOMING = "incoming"
    OUTGOING = "outgoing"


class CorrespondenceStatus(StrEnum):
    NEW = "neu"
    IN_PROGRESS = "in_bearbeitung"
    DONE = "erledigt"


class SourceType(StrEnum):
    EMAIL_IMPORT = "email_import"
    MANUAL_UPLOAD = "manual_upload"
    MANUAL_ENTRY = "manual_entry"


class OCRStatus(StrEnum):
    PENDING = "pending"
    COMPLETED = "completed"
    FAILED = "failed"
    NOT_APPLICABLE = "not_applicable"


class ProcessingStatus(StrEnum):
    PROCESSED = "processed"
    FAILED = "failed"
    SKIPPED_DUPLICATE = "skipped_duplicate"
    INVALID = "invalid"


class ProposalStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class DocumentRole(StrEnum):
    SOURCE_SCAN = "source_scan"
    SUPPORTING_DOCUMENT = "supporting_document"


class MailboxProcessingMode(StrEnum):
    SCAN_IMPORT = "scan_import"
    GENERAL_TRIAGE = "general_triage"


class MailItemStatus(StrEnum):
    NEW = "neu"
    IN_PROGRESS = "in_bearbeitung"
    WAITING = "wartet_aktion"
    FORWARDED = "weitergeleitet"
    REPLIED = "beantwortet"
    CLOSED = "geschlossen"
    ERROR = "fehler"


class MailItemActionType(StrEnum):
    FORWARD = "forward"
    REPLY = "reply"
    NONE = "none"
