from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, Field

from app.models.enums import (
    BookingSource,
    BookingStatus,
    DocumentType,
    InternetMedium,
    LeaseStatus,
    NotificationStatus,
    OccupancyMode,
    PartyType,
)
from app.schemas.common import ORMModel


class BuildingCreate(BaseModel):
    name: str
    street: str | None = None
    postal_code: str | None = None
    city: str | None = None
    notes: str | None = None


class BuildingUpdate(BaseModel):
    name: str | None = None
    street: str | None = None
    postal_code: str | None = None
    city: str | None = None
    notes: str | None = None


class BuildingRead(ORMModel):
    id: int
    name: str
    street: str | None
    postal_code: str | None
    city: str | None
    notes: str | None


class FloorCreate(BaseModel):
    building_id: int
    name: str
    floor_number: int
    floorplan_object_key: str | None = None
    image_object_key: str | None = None
    notes: str | None = None


class FloorUpdate(BaseModel):
    name: str | None = None
    floor_number: int | None = None
    floorplan_object_key: str | None = None
    image_object_key: str | None = None
    notes: str | None = None


class FloorRead(ORMModel):
    id: int
    building_id: int
    name: str
    floor_number: int
    floorplan_object_key: str | None
    image_object_key: str | None
    notes: str | None


class RoomCreate(BaseModel):
    floor_id: int
    room_code: str
    name: str
    usage_type: str
    occupancy_mode: OccupancyMode = OccupancyMode.LEASABLE
    rentable: bool = False
    bookable: bool = False
    public_bookable: bool = False
    is_active: bool = True
    capacity: int | None = None
    public_description: str | None = None
    cleaning_rate_daily: Decimal | None = None
    length_m: Decimal | None = None
    width_m: Decimal | None = None
    height_m: Decimal | None = None
    area_sqm: Decimal | None = None
    meter_number: str | None = None
    has_internet: bool = False


class RoomUpdate(BaseModel):
    floor_id: int | None = None
    room_code: str | None = None
    name: str | None = None
    usage_type: str | None = None
    occupancy_mode: OccupancyMode | None = None
    rentable: bool | None = None
    bookable: bool | None = None
    public_bookable: bool | None = None
    is_active: bool | None = None
    capacity: int | None = None
    public_description: str | None = None
    cleaning_rate_daily: Decimal | None = None
    length_m: Decimal | None = None
    width_m: Decimal | None = None
    height_m: Decimal | None = None
    area_sqm: Decimal | None = None
    meter_number: str | None = None
    has_internet: bool | None = None


class RoomRead(ORMModel):
    id: int
    floor_id: int
    room_code: str
    name: str
    usage_type: str
    occupancy_mode: OccupancyMode
    rentable: bool
    bookable: bool
    public_bookable: bool
    is_active: bool
    capacity: int | None
    public_description: str | None
    cleaning_rate_daily: Decimal | None
    length_m: Decimal | None
    width_m: Decimal | None
    height_m: Decimal | None
    area_sqm: Decimal | None
    meter_number: str | None
    has_internet: bool


class RoomStatusRead(BaseModel):
    room_id: int
    status: str


class PartyCreate(BaseModel):
    party_type: PartyType
    name: str
    email: str | None = None
    phone: str | None = None
    street: str | None = None
    postal_code: str | None = None
    city: str | None = None
    is_active: bool = True
    notes: str | None = None


class PartyUpdate(BaseModel):
    party_type: PartyType | None = None
    name: str | None = None
    email: str | None = None
    phone: str | None = None
    street: str | None = None
    postal_code: str | None = None
    city: str | None = None
    is_active: bool | None = None
    notes: str | None = None


class PartyRead(ORMModel):
    id: int
    party_type: PartyType
    name: str
    email: str | None
    phone: str | None
    street: str | None
    postal_code: str | None
    city: str | None
    is_active: bool
    notes: str | None


class LeaseCreate(BaseModel):
    room_id: int
    party_id: int
    contract_reference: str | None = None
    start_date: date
    end_date: date | None = None
    notice_period_days: int | None = None
    monthly_rent: Decimal
    deposit_amount: Decimal | None = None
    currency: str = "EUR"
    status: LeaseStatus = LeaseStatus.DRAFT
    notes: str | None = None


class LeaseUpdate(BaseModel):
    party_id: int | None = None
    contract_reference: str | None = None
    start_date: date | None = None
    end_date: date | None = None
    notice_period_days: int | None = None
    monthly_rent: Decimal | None = None
    deposit_amount: Decimal | None = None
    currency: str | None = None
    status: LeaseStatus | None = None
    notes: str | None = None


class LeaseRead(ORMModel):
    id: int
    room_id: int
    party_id: int
    contract_reference: str | None
    start_date: date
    end_date: date | None
    notice_period_days: int | None
    monthly_rent: Decimal
    deposit_amount: Decimal | None
    currency: str
    status: LeaseStatus
    notes: str | None


class InternalRoomAssignmentCreate(BaseModel):
    room_id: int
    party_id: int
    start_date: date
    notes: str | None = None


class InternalRoomAssignmentEnd(BaseModel):
    end_date: date
    notes: str | None = None


class InternalRoomAssignmentRead(ORMModel):
    id: int
    room_id: int
    party_id: int
    assigned_by_user_id: int | None
    start_date: date
    end_date: date | None
    notes: str | None
    created_at: datetime
    updated_at: datetime


class BookingCreate(BaseModel):
    room_id: int
    party_id: int
    title: str
    start_at: datetime
    end_at: datetime
    purpose: str | None = None
    attendee_count: int | None = None
    notes: str | None = None


class BookingUpdate(BaseModel):
    #: Settable so a booking can be moved between rooms -- the calendar's
    #: rooms view drags between lanes, which is a room change.
    room_id: int | None = None
    party_id: int | None = None
    title: str | None = None
    start_at: datetime | None = None
    end_at: datetime | None = None
    status: BookingStatus | None = None
    purpose: str | None = None
    attendee_count: int | None = None
    notes: str | None = None


class BookingRead(ORMModel):
    id: int
    room_id: int
    party_id: int
    title: str
    start_at: datetime
    end_at: datetime
    status: BookingStatus
    source: BookingSource
    created_by_user_id: int | None
    purpose: str | None
    attendee_count: int | None
    notes: str | None


class BookingConflict(BaseModel):
    kind: str
    start_at: datetime | date | None
    end_at: datetime | date | None


class BookingCreateRead(BookingRead):
    """Staff create response.

    `conflicts` is advisory, not a refusal: staff must still be able to record
    a competing request against a room that is already taken and decide between
    them at approval time, which is where the check actually bites.
    """

    conflicts: list[BookingConflict] = []


class KeyCreate(BaseModel):
    room_id: int | None = None
    key_code: str
    description: str | None = None
    hanging_location: str | None = None
    master_key: bool = False
    is_active: bool = True
    total_quantity: int = Field(default=1, ge=1)


class KeyUpdate(BaseModel):
    room_id: int | None = None
    key_code: str | None = None
    description: str | None = None
    hanging_location: str | None = None
    master_key: bool | None = None
    is_active: bool | None = None
    total_quantity: int | None = Field(default=None, ge=1)


class KeyRead(ORMModel):
    id: int
    room_id: int | None
    key_code: str
    description: str | None
    hanging_location: str | None
    master_key: bool
    is_active: bool
    total_quantity: int
    available_quantity: int


class KeyAssignmentCreate(BaseModel):
    key_id: int
    room_id: int
    party_id: int
    issued_at: datetime
    issue_note: str | None = None


class KeyAssignmentReturn(BaseModel):
    returned_at: datetime
    return_note: str | None = None


class KeyAssignmentRead(ORMModel):
    id: int
    key_id: int
    room_id: int
    party_id: int
    issued_at: datetime
    returned_at: datetime | None
    issue_note: str | None
    issue_receipt_object_key: str | None
    issue_receipt_filename: str | None
    issue_receipt_mime_type: str | None
    issue_receipt_size: int | None
    return_note: str | None


class EquipmentCreate(BaseModel):
    name: str
    category: str | None = None
    notes: str | None = None


class EquipmentUpdate(BaseModel):
    name: str | None = None
    category: str | None = None
    notes: str | None = None


class EquipmentRead(ORMModel):
    id: int
    name: str
    category: str | None
    notes: str | None


class RoomEquipmentCreate(BaseModel):
    room_id: int
    equipment_id: int
    quantity: int = 1
    fixed: bool = True
    notes: str | None = None


class RoomEquipmentUpdate(BaseModel):
    quantity: int | None = None
    fixed: bool | None = None
    notes: str | None = None


class RoomEquipmentRead(ORMModel):
    id: int
    room_id: int
    equipment_id: int
    quantity: int
    fixed: bool
    notes: str | None


class InternetConnectionCreate(BaseModel):
    room_id: int
    medium: InternetMedium
    channel: str | None = None
    provider: str | None = None
    is_active: bool = True
    notes: str | None = None


class InternetConnectionRead(ORMModel):
    id: int
    room_id: int
    medium: InternetMedium
    channel: str | None
    provider: str | None
    is_active: bool
    notes: str | None


class DocumentRead(ORMModel):
    id: int
    room_id: int | None
    lease_id: int | None
    uploaded_by_user_id: int | None
    document_type: DocumentType
    title: str
    object_key: str
    original_filename: str | None
    mime_type: str | None
    file_size: int | None
    uploaded_at: datetime
    notes: str | None


class NotificationRead(ORMModel):
    id: int
    user_id: int
    title: str
    message: str
    link: str | None
    status: NotificationStatus
    read_at: datetime | None


class DashboardRead(BaseModel):
    total_rooms: int
    active_rooms: int
    occupied_rooms: int
    rooms_booked_now: int
    expiring_leases_30d: int
    unreturned_keys: int


class ActionCenterItem(BaseModel):
    code: str
    severity: str
    count: int
    message: str
