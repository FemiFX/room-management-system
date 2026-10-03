from enum import StrEnum


class Role(StrEnum):
    SUPER_ADMIN = "super_admin"
    ADMIN = "admin"
    EDITOR = "editor"
    VIEWER = "viewer"
    # Booking-only tier for synced account holders. Deliberately absent
    # from every require_role(...) tuple, so writes are denied by default;
    # reads are contained by MemberScopeMiddleware, not by role tuples.
    MEMBER = "member"


#: Roles that may use the admin surface. MEMBER is the only exclusion.
STAFF_ROLES = (Role.SUPER_ADMIN, Role.ADMIN, Role.EDITOR, Role.VIEWER)


class OccupancyMode(StrEnum):
    LEASABLE = "leasable"
    BOOKABLE = "bookable"
    INTERNAL = "internal"
    MIXED = "mixed"


class LeaseStatus(StrEnum):
    DRAFT = "draft"
    ACTIVE = "active"
    EXPIRED = "expired"
    TERMINATED = "terminated"
    CANCELLED = "cancelled"


class BookingStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    CANCELLED = "cancelled"
    COMPLETED = "completed"


class InternetMedium(StrEnum):
    LAN = "lan"
    WIFI = "wifi"
    FIBER = "fiber"
    COAX = "coax"


class DocumentType(StrEnum):
    CONTRACT = "contract"
    FLOORPLAN = "floorplan"
    HANDOVER_PROTOCOL = "handover_protocol"
    INVOICE = "invoice"
    PHOTO = "photo"
    INSPECTION = "inspection"
    #: Proof of liability cover, attached to a booking by the requester or staff.
    INSURANCE = "insurance"
    OTHER = "other"


class NotificationStatus(StrEnum):
    UNREAD = "unread"
    READ = "read"


class PartyType(StrEnum):
    PERSON = "person"
    ORGANIZATION = "organization"
    TEAM = "team"
    # Public booking requesters. Kept separate from PERSON so a stranger's
    # request can never be matched onto a real staff or tenant record.
    EXTERNAL = "external"


class BookingSource(StrEnum):
    STAFF = "staff"
    PUBLIC = "public"
    INTERNAL = "internal"
