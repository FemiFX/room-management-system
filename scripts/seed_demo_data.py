from __future__ import annotations

import argparse
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
import sys

from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db.base import Base
from app.db.session import get_engine, get_session_factory
from app.models.audit_log import AuditLog
from app.models.booking import Booking
from app.models.booking_request import BookingRequest
from app.models.booking_service import BookingService
from app.models.room_service import RoomService
from app.models.building import Building
from app.models.document import Document
from app.models.enums import (
    BookingSource,
    BookingStatus,
    DocumentType,
    InternetMedium,
    LeaseStatus,
    NotificationStatus,
    OccupancyMode,
    PartyType,
    Role,
)
from app.models.equipment import Equipment, RoomEquipment
from app.models.floor import Floor
from app.models.internet_connection import InternetConnection
from app.models.key import Key, KeyAssignment
from app.models.lease import Lease
from app.models.notification import Notification
from app.models.party import Party
from app.models.room import Room
from app.models.user import User
from app.storage.minio_client import upload_bytes


def ensure_schema() -> None:
    engine = get_engine()
    Base.metadata.create_all(bind=engine)


def clear_all_data(db: Session) -> None:
    # Users point at parties (users.party_id, migration 20260828_0015) and that
    # FK is not ON DELETE SET NULL, so a linked user blocks the Party delete
    # below. Unlink first; the users themselves are deleted at the end anyway,
    # but any row this script does not own would otherwise abort the reset.
    db.execute(update(User).values(party_id=None))

    # Reverse dependency order to satisfy FK constraints.
    for model in [
        Notification,
        Document,
        RoomService,
        RoomEquipment,
        InternetConnection,
        KeyAssignment,
        Key,
        Booking,
        Lease,
        Party,
        Room,
        Floor,
        Building,
        AuditLog,
        User,
    ]:
        db.execute(delete(model))
    db.commit()


def get_or_create_user(db: Session, *, email: str, display_name: str, role: Role, is_active: bool, oidc_subject: str | None = None) -> User:
    user = db.scalar(select(User).where(User.email == email))
    if user is None:
        user = User(email=email, display_name=display_name, role=role, is_active=is_active, oidc_subject=oidc_subject)
        db.add(user)
    else:
        user.display_name = display_name
        user.role = role
        user.is_active = is_active
        if oidc_subject is not None:
            user.oidc_subject = oidc_subject
    db.flush()
    return user


def get_or_create_building(db: Session, *, name: str, city: str, street: str) -> Building:
    b = db.scalar(select(Building).where(Building.name == name))
    if b is None:
        b = Building(name=name, city=city, street=street)
        db.add(b)
    else:
        b.city = city
        b.street = street
    db.flush()
    return b


def get_or_create_floor(db: Session, *, building: Building, name: str, floor_number: int) -> Floor:
    f = db.scalar(select(Floor).where(Floor.building_id == building.id, Floor.floor_number == floor_number))
    if f is None:
        f = Floor(building_id=building.id, name=name, floor_number=floor_number)
        db.add(f)
    else:
        f.name = name
    db.flush()
    return f


def get_or_create_room(
    db: Session,
    *,
    floor: Floor,
    room_code: str,
    name: str,
    usage_type: str,
    occupancy_mode: OccupancyMode,
    rentable: bool,
    bookable: bool,
    meter_number: str | None,
    has_internet: bool,
) -> Room:
    room = db.scalar(select(Room).where(Room.room_code == room_code))
    if room is None:
        room = Room(
            floor_id=floor.id,
            room_code=room_code,
            name=name,
            usage_type=usage_type,
            occupancy_mode=occupancy_mode,
            rentable=rentable,
            bookable=bookable,
            meter_number=meter_number,
            has_internet=has_internet,
            is_active=True,
        )
        db.add(room)
    else:
        room.floor_id = floor.id
        room.name = name
        room.usage_type = usage_type
        room.occupancy_mode = occupancy_mode
        room.rentable = rentable
        room.bookable = bookable
        room.meter_number = meter_number
        room.has_internet = has_internet
        room.is_active = True
    db.flush()
    return room


def get_or_create_party(db: Session, *, party_type: PartyType, name: str, email: str | None = None) -> Party:
    party = db.scalar(select(Party).where(Party.name == name, Party.party_type == party_type))
    if party is None:
        party = Party(party_type=party_type, name=name, email=email, is_active=True)
        db.add(party)
    else:
        party.email = email
        party.is_active = True
    db.flush()
    return party


def get_or_create_lease(
    db: Session,
    *,
    contract_reference: str,
    room: Room,
    party: Party,
    start_date: date,
    end_date: date | None,
    monthly_rent: Decimal,
    status: LeaseStatus,
) -> Lease:
    lease = db.scalar(select(Lease).where(Lease.contract_reference == contract_reference))
    if lease is None:
        lease = Lease(
            contract_reference=contract_reference,
            room_id=room.id,
            party_id=party.id,
            start_date=start_date,
            end_date=end_date,
            monthly_rent=monthly_rent,
            currency="EUR",
            status=status,
            notice_period_days=90,
        )
        db.add(lease)
    else:
        lease.room_id = room.id
        lease.party_id = party.id
        lease.start_date = start_date
        lease.end_date = end_date
        lease.monthly_rent = monthly_rent
        lease.currency = "EUR"
        lease.status = status
        lease.notice_period_days = 90
    db.flush()
    return lease


def get_or_create_booking(
    db: Session,
    *,
    room: Room,
    party: Party,
    title: str,
    start_at: datetime,
    end_at: datetime,
    status: BookingStatus,
    source: BookingSource = BookingSource.STAFF,
    created_by: User | None = None,
) -> Booking:
    booking = db.scalar(select(Booking).where(Booking.room_id == room.id, Booking.title == title, Booking.start_at == start_at))
    if booking is None:
        booking = Booking(
            room_id=room.id,
            party_id=party.id,
            title=title,
            start_at=start_at,
            end_at=end_at,
            status=status,
            attendee_count=12,
        )
        db.add(booking)
    else:
        booking.party_id = party.id
        booking.end_at = end_at
        booking.status = status
        booking.attendee_count = 12
    booking.source = source
    booking.created_by_user_id = created_by.id if created_by else None
    db.flush()
    return booking


def get_or_create_key(
    db: Session,
    *,
    key_code: str,
    description: str,
    hanging_location: str | None = None,
    master_key: bool = False,
    total_quantity: int = 1,
) -> Key:
    key = db.scalar(select(Key).where(Key.key_code == key_code))
    if key is None:
        key = Key(
            key_code=key_code,
            description=description,
            hanging_location=hanging_location,
            master_key=master_key,
            is_active=True,
            total_quantity=total_quantity,
            available_quantity=total_quantity,
        )
        db.add(key)
    else:
        key.description = description
        key.hanging_location = hanging_location
        key.master_key = master_key
        key.is_active = True
        key.total_quantity = total_quantity
        if key.available_quantity > total_quantity:
            key.available_quantity = total_quantity
    db.flush()
    return key


def sync_key_inventory(db: Session, key: Key) -> None:
    open_assignments = db.scalar(
        select(func.count(KeyAssignment.id)).where(
            KeyAssignment.key_id == key.id,
            KeyAssignment.returned_at.is_(None),
        )
    ) or 0
    key.available_quantity = max(0, key.total_quantity - int(open_assignments))


def get_or_create_equipment(db: Session, *, name: str, category: str) -> Equipment:
    eq = db.scalar(select(Equipment).where(Equipment.name == name))
    if eq is None:
        eq = Equipment(name=name, category=category)
        db.add(eq)
    else:
        eq.category = category
    db.flush()
    return eq


def attach_equipment(db: Session, *, room: Room, equipment: Equipment, quantity: int, fixed: bool = True) -> None:
    link = db.scalar(select(RoomEquipment).where(RoomEquipment.room_id == room.id, RoomEquipment.equipment_id == equipment.id))
    if link is None:
        link = RoomEquipment(room_id=room.id, equipment_id=equipment.id, quantity=quantity, fixed=fixed)
        db.add(link)
    else:
        link.quantity = quantity
        link.fixed = fixed


def add_internet(db: Session, *, room: Room, medium: InternetMedium, channel: str, provider: str = "NetCom") -> None:
    conn = db.scalar(select(InternetConnection).where(InternetConnection.room_id == room.id, InternetConnection.medium == medium, InternetConnection.channel == channel))
    if conn is None:
        conn = InternetConnection(room_id=room.id, medium=medium, channel=channel, provider=provider, is_active=True)
        db.add(conn)
    else:
        conn.provider = provider
        conn.is_active = True


def get_or_create_document(
    db: Session,
    *,
    object_key: str,
    title: str,
    document_type: DocumentType,
    uploader: User,
    room: Room | None = None,
    lease: Lease | None = None,
) -> Document:
    doc = db.scalar(select(Document).where(Document.object_key == object_key))
    filename = object_key.split("/")[-1]
    if doc is None:
        doc = Document(
            room_id=room.id if room else None,
            lease_id=lease.id if lease else None,
            uploaded_by_user_id=uploader.id,
            document_type=document_type,
            title=title,
            object_key=object_key,
            original_filename=filename,
            mime_type="application/pdf",
            file_size=2048,
            uploaded_at=datetime.now(UTC),
            notes="Demo seed document",
        )
        db.add(doc)
    else:
        doc.title = title
        doc.document_type = document_type
        doc.room_id = room.id if room else None
        doc.lease_id = lease.id if lease else None
        doc.uploaded_by_user_id = uploader.id
        doc.uploaded_at = datetime.now(UTC)

    # Best effort upload so presigned URLs can resolve.
    try:
        upload_bytes(
            object_key=object_key,
            data=b"%PDF-1.4\n% Demo seeded file\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF",
            content_type="application/pdf",
        )
    except Exception:
        pass

    db.flush()
    return doc


def add_notification(db: Session, *, user: User, title: str, message: str, status: NotificationStatus) -> None:
    existing = db.scalar(select(Notification).where(Notification.user_id == user.id, Notification.title == title))
    if existing is None:
        db.add(
            Notification(
                user_id=user.id,
                title=title,
                message=message,
                status=status,
                read_at=None if status == NotificationStatus.UNREAD else datetime.now(UTC),
            )
        )
    else:
        existing.message = message
        existing.status = status
        existing.read_at = None if status == NotificationStatus.UNREAD else datetime.now(UTC)


def seed(db: Session) -> None:
    today = date.today()
    now = datetime.now(UTC)

    # Users
    admin = get_or_create_user(
        db,
        email="admin@example.com",
        display_name="System Admin",
        role=Role.SUPER_ADMIN,
        is_active=True,
    )
    get_or_create_user(db, email="ops@example.com", display_name="Operations Lead", role=Role.ADMIN, is_active=True)
    get_or_create_user(db, email="editor@example.com", display_name="Space Coordinator", role=Role.EDITOR, is_active=True)
    get_or_create_user(db, email="viewer@example.com", display_name="Finance Viewer", role=Role.VIEWER, is_active=True)
    get_or_create_user(db, email="inactive@example.com", display_name="Inactive User", role=Role.VIEWER, is_active=False)

    # Buildings / floors / rooms
    hq = get_or_create_building(db, name="Main Campus", city="Berlin", street="Alexanderplatz 10")
    annex = get_or_create_building(db, name="Annex Site", city="Berlin", street="Schwedter Str. 22")

    hq_gf = get_or_create_floor(db, building=hq, name="Ground Floor", floor_number=0)
    hq_1f = get_or_create_floor(db, building=hq, name="First Floor", floor_number=1)
    annex_gf = get_or_create_floor(db, building=annex, name="Ground Floor", floor_number=0)

    rooms = {
        "EG-101": get_or_create_room(db, floor=hq_gf, room_code="EG-101", name="Reception", usage_type="front_desk", occupancy_mode=OccupancyMode.INTERNAL, rentable=False, bookable=False, meter_number="MTR-1001", has_internet=True),
        "EG-102": get_or_create_room(db, floor=hq_gf, room_code="EG-102", name="Meeting Atlas", usage_type="meeting", occupancy_mode=OccupancyMode.BOOKABLE, rentable=False, bookable=True, meter_number="MTR-1002", has_internet=True),
        "EG-103": get_or_create_room(db, floor=hq_gf, room_code="EG-103", name="Office West", usage_type="office", occupancy_mode=OccupancyMode.LEASABLE, rentable=True, bookable=False, meter_number="MTR-1003", has_internet=True),
        "EG-104": get_or_create_room(db, floor=hq_gf, room_code="EG-104", name="Studio North", usage_type="studio", occupancy_mode=OccupancyMode.MIXED, rentable=True, bookable=True, meter_number="MTR-1004", has_internet=True),
        "OG-201": get_or_create_room(db, floor=hq_1f, room_code="OG-201", name="Office East", usage_type="office", occupancy_mode=OccupancyMode.LEASABLE, rentable=True, bookable=False, meter_number="MTR-1201", has_internet=True),
        "OG-202": get_or_create_room(db, floor=hq_1f, room_code="OG-202", name="Training Room", usage_type="training", occupancy_mode=OccupancyMode.BOOKABLE, rentable=False, bookable=True, meter_number="MTR-1202", has_internet=True),
        "OG-203": get_or_create_room(db, floor=hq_1f, room_code="OG-203", name="Storage", usage_type="storage", occupancy_mode=OccupancyMode.INTERNAL, rentable=False, bookable=False, meter_number="MTR-1203", has_internet=False),
        "AN-01": get_or_create_room(db, floor=annex_gf, room_code="AN-01", name="Workshop", usage_type="workshop", occupancy_mode=OccupancyMode.MIXED, rentable=True, bookable=True, meter_number="MTR-2001", has_internet=True),
        "AN-02": get_or_create_room(db, floor=annex_gf, room_code="AN-02", name="Archive", usage_type="archive", occupancy_mode=OccupancyMode.INTERNAL, rentable=False, bookable=False, meter_number="MTR-2002", has_internet=False),
        "AN-03": get_or_create_room(db, floor=annex_gf, room_code="AN-03", name="Team Office", usage_type="office", occupancy_mode=OccupancyMode.LEASABLE, rentable=True, bookable=False, meter_number="MTR-2003", has_internet=True),
    }

    # Parties
    acme = get_or_create_party(db, party_type=PartyType.ORGANIZATION, name="Acme GmbH", email="contact@acme.example")
    northwind = get_or_create_party(db, party_type=PartyType.ORGANIZATION, name="Northwind Labs", email="ops@northwind.example")
    civic_team = get_or_create_party(db, party_type=PartyType.TEAM, name="Civic Program Team", email="team@civic.example")
    eventcrew = get_or_create_party(db, party_type=PartyType.ORGANIZATION, name="Event Crew Alpha", email="events@crew.example")
    jane = get_or_create_party(db, party_type=PartyType.PERSON, name="Jane Miller", email="jane@example.com")
    marco = get_or_create_party(db, party_type=PartyType.PERSON, name="Marco Rossi", email="marco@example.com")

    # A member account, linked to its contact record. In production the hourly
    # Nextcloud sync writes users.party_id; nothing does it in a demo database,
    # and an account without a party cannot book -- which left the whole member
    # portal showing one "not linked to a contact record" notice and nothing
    # else. Log in with this email and role "member" to see the portal.
    member = get_or_create_user(
        db,
        email="jane@example.com",
        display_name="Jane Miller",
        role=Role.MEMBER,
        is_active=True,
    )
    member.party_id = jane.id
    db.flush()

    # Leases
    lease_1 = get_or_create_lease(
        db,
        contract_reference="L-2026-001",
        room=rooms["EG-103"],
        party=acme,
        start_date=today - timedelta(days=220),
        end_date=today + timedelta(days=180),
        monthly_rent=Decimal("3250.00"),
        status=LeaseStatus.ACTIVE,
    )
    lease_2 = get_or_create_lease(
        db,
        contract_reference="L-2026-002",
        room=rooms["OG-201"],
        party=northwind,
        start_date=today - timedelta(days=140),
        end_date=today + timedelta(days=20),
        monthly_rent=Decimal("2875.00"),
        status=LeaseStatus.ACTIVE,
    )
    get_or_create_lease(
        db,
        contract_reference="L-2025-015",
        room=rooms["AN-03"],
        party=civic_team,
        start_date=today - timedelta(days=500),
        end_date=today - timedelta(days=40),
        monthly_rent=Decimal("1900.00"),
        status=LeaseStatus.EXPIRED,
    )
    get_or_create_lease(
        db,
        contract_reference="L-2026-010",
        room=rooms["EG-104"],
        party=jane,
        start_date=today + timedelta(days=14),
        end_date=today + timedelta(days=380),
        monthly_rent=Decimal("2100.00"),
        status=LeaseStatus.DRAFT,
    )

    # Bookings (pending + approved)
    get_or_create_booking(
        db,
        room=rooms["EG-102"],
        party=eventcrew,
        title="Weekly Ops Sync",
        start_at=now - timedelta(hours=1),
        end_at=now + timedelta(hours=2),
        status=BookingStatus.APPROVED,
    )
    get_or_create_booking(
        db,
        room=rooms["OG-202"],
        party=eventcrew,
        title="Community Workshop",
        start_at=now + timedelta(days=1, hours=2),
        end_at=now + timedelta(days=1, hours=5),
        status=BookingStatus.APPROVED,
    )
    get_or_create_booking(
        db,
        room=rooms["AN-01"],
        party=civic_team,
        title="Equipment Intake",
        start_at=now + timedelta(days=3, hours=1),
        end_at=now + timedelta(days=3, hours=4),
        status=BookingStatus.PENDING,
    )

    # Keys and assignments
    key_eg = get_or_create_key(
        db,
        key_code="K-EG103",
        description="Office West",
        hanging_location="Reception Board",
        total_quantity=2,
    )
    key_og = get_or_create_key(
        db,
        key_code="K-OG201",
        description="Office East",
        hanging_location="Facility Cabinet",
        total_quantity=1,
    )
    key_master = get_or_create_key(
        db,
        key_code="MASTER-01",
        description="Master Key",
        hanging_location="Security Desk",
        master_key=True,
        total_quantity=1,
    )

    def upsert_assignment(key: Key, room: Room, party: Party, issued_at: datetime, returned_at: datetime | None) -> None:
        assignment = db.scalar(
            select(KeyAssignment).where(
                KeyAssignment.key_id == key.id,
                KeyAssignment.room_id == room.id,
                KeyAssignment.party_id == party.id,
                KeyAssignment.issued_at == issued_at,
            )
        )
        if assignment is None:
            assignment = KeyAssignment(
                key_id=key.id,
                room_id=room.id,
                party_id=party.id,
                issued_at=issued_at,
                returned_at=returned_at,
            )
            db.add(assignment)
        else:
            assignment.returned_at = returned_at

    upsert_assignment(key_eg, rooms["EG-103"], jane, now - timedelta(days=10), None)
    upsert_assignment(key_eg, rooms["EG-103"], marco, now - timedelta(days=40), now - timedelta(days=5))
    upsert_assignment(key_og, rooms["OG-201"], marco, now - timedelta(days=45), None)
    upsert_assignment(key_master, rooms["EG-101"], jane, now - timedelta(days=120), None)
    for key in (key_eg, key_og, key_master):
        sync_key_inventory(db, key)

    # Equipment + room equipment
    projector = get_or_create_equipment(db, name="Projector", category="AV")
    desk = get_or_create_equipment(db, name="Desk", category="Furniture")
    chair = get_or_create_equipment(db, name="Ergonomic Chair", category="Furniture")
    whiteboard = get_or_create_equipment(db, name="Whiteboard", category="Collaboration")
    display = get_or_create_equipment(db, name="4K Display", category="AV")

    attach_equipment(db, room=rooms["EG-102"], equipment=projector, quantity=1)
    attach_equipment(db, room=rooms["EG-102"], equipment=whiteboard, quantity=2)
    attach_equipment(db, room=rooms["EG-103"], equipment=desk, quantity=8)
    attach_equipment(db, room=rooms["EG-103"], equipment=chair, quantity=8)
    attach_equipment(db, room=rooms["OG-202"], equipment=display, quantity=1)
    attach_equipment(db, room=rooms["AN-01"], equipment=desk, quantity=6)

    # ── Public booking surface ──────────────────────────────────────────
    # The three spaces that are let out, in their own two buildings, so the
    # demo data has the shape of the real thing. Everything else stays
    # internal: the form at /book lists `is_active AND public_bookable`, and
    # these three are the only rooms carrying that flag.
    main_building = get_or_create_building(db, name="Hauptgebäude", city="Berlin", street="Beispielstraße 1")
    annex = get_or_create_building(db, name="Nebengebäude", city="Berlin", street="Beispielstraße 3")
    main_building_gf = get_or_create_floor(db, building=main_building, name="Erdgeschoss", floor_number=0)
    annex_gf = get_or_create_floor(db, building=annex, name="Erdgeschoss", floor_number=0)

    # The names are the ones the public sees on the room cards, so they carry
    # the building with them -- "Galerie" alone says nothing to a visitor.
    public_rooms = {
        "HG-BIB": get_or_create_room(
            db, floor=main_building_gf, room_code="HG-BIB", name="Hauptgebäude – Bibliotheksraum",
            usage_type="event", occupancy_mode=OccupancyMode.BOOKABLE, rentable=False,
            bookable=True, meter_number=None, has_internet=True,
        ),
        "NB-GAL": get_or_create_room(
            db, floor=annex_gf, room_code="NB-GAL", name="Galerie (Nebengebäude, Erdgeschoss)",
            usage_type="event", occupancy_mode=OccupancyMode.BOOKABLE, rentable=False,
            bookable=True, meter_number=None, has_internet=True,
        ),
        "NB-KIN": get_or_create_room(
            db, floor=annex_gf, room_code="NB-KIN", name="Kinderbetreuungsraum (Nebengebäude, Erdgeschoss)",
            usage_type="event", occupancy_mode=OccupancyMode.BOOKABLE, rentable=False,
            bookable=True, meter_number=None, has_internet=True,
        ),
    }
    rooms.update(public_rooms)

    # The cleaning rate stays: it is computed and stored on every booking for
    # the invoice. It is simply no longer quoted on the public pages.
    for code, capacity, rate, description in [
        ("HG-BIB", 75, Decimal("90.00"),
         "Unser Veranstaltungsraum in der Bibliothek – für Lesungen, Vorträge, "
         "Workshops und Seminare."),
        ("NB-GAL", 150, Decimal("150.00"),
         "Der große Raum im Erdgeschoss des Nebengebäudes – für Ausstellungen, Empfänge, "
         "Feiern und Veranstaltungen mit vielen Gästen."),
        ("NB-KIN", 20, Decimal("45.00"),
         "Ruhiger, kindgerecht eingerichteter Raum im Nebengebäude – für Kinderbetreuung "
         "parallel zu eurer Veranstaltung oder für kleine Runden."),
    ]:
        room = rooms[code]
        room.public_bookable = True
        room.capacity = capacity
        room.cleaning_rate_daily = rate
        room.public_description = description

    # The office rooms were on the public form while it was being built.
    for code in ("AN-01", "OG-202", "EG-104"):
        rooms[code].public_bookable = False

    # What the three rooms hold. `fixed` is installed kit: the form lists it
    # as part of the room, without a quantity field.
    attach_equipment(db, room=rooms["HG-BIB"], equipment=projector, quantity=1, fixed=True)
    attach_equipment(db, room=rooms["HG-BIB"], equipment=whiteboard, quantity=2, fixed=True)
    attach_equipment(db, room=rooms["NB-GAL"], equipment=display, quantity=1, fixed=True)
    attach_equipment(db, room=rooms["NB-KIN"], equipment=whiteboard, quantity=1, fixed=True)

    rooms["EG-102"].capacity = 12
    db.flush()

    # Loose equipment a public requester can ask for, on top of what is
    # already attached above.
    folding_chair = get_or_create_equipment(db, name="Folding Chair", category="Furniture")
    beamer = get_or_create_equipment(db, name="Beamer", category="AV")
    attach_equipment(db, room=rooms["HG-BIB"], equipment=folding_chair, quantity=75, fixed=False)
    attach_equipment(db, room=rooms["HG-BIB"], equipment=desk, quantity=10, fixed=False)
    attach_equipment(db, room=rooms["NB-GAL"], equipment=folding_chair, quantity=150, fixed=False)
    attach_equipment(db, room=rooms["NB-GAL"], equipment=beamer, quantity=1, fixed=False)
    attach_equipment(db, room=rooms["NB-KIN"], equipment=folding_chair, quantity=20, fixed=False)
    attach_equipment(db, room=rooms["AN-01"], equipment=folding_chair, quantity=60, fixed=False)
    attach_equipment(db, room=rooms["AN-01"], equipment=beamer, quantity=2, fixed=False)

    # Bookable extra services for the public form.
    for code, name, description, sort_order in [
        ("technician", "Technik-Betreuung", "Ton, Licht und Beamer werden während der Veranstaltung betreut.", 1),
        ("usher", "Einlass & Empfang", "Unterstützung am Eingang vor und während der Veranstaltung.", 2),
    ]:
        service = db.scalar(select(BookingService).where(BookingService.code == code))
        if service is None:
            db.add(BookingService(code=code, name=name, description=description, is_active=True, sort_order=sort_order))
        else:
            service.name = name
            service.description = description
            service.is_active = True
            service.sort_order = sort_order
    db.flush()

    # Which rooms offer which services. Not every room gets a technician --
    # that is the whole point of the room_services table.
    offerings = {
        "HG-BIB": ["technician", "usher"],
        "NB-GAL": ["technician", "usher"],
        "NB-KIN": [],
        "AN-01": ["technician", "usher"],
        "OG-202": ["usher"],
    }
    for room_code, service_codes in offerings.items():
        room = rooms[room_code]
        for code in service_codes:
            service = db.scalar(select(BookingService).where(BookingService.code == code))
            exists = db.scalar(
                select(RoomService).where(
                    RoomService.room_id == room.id, RoomService.service_id == service.id
                )
            )
            if exists is None:
                db.add(RoomService(room_id=room.id, service_id=service.id))
    db.flush()

    # A little future traffic so the public availability calendar has content.
    get_or_create_booking(
        db, room=rooms["HG-BIB"], party=eventcrew, title="Vereinsworkshop",
        start_at=now + timedelta(days=8, hours=2), end_at=now + timedelta(days=8, hours=8),
        status=BookingStatus.APPROVED,
    )
    get_or_create_booking(
        db, room=rooms["NB-GAL"], party=civic_team, title="Lesung und Gespräch",
        start_at=now + timedelta(days=12, hours=4), end_at=now + timedelta(days=12, hours=9),
        status=BookingStatus.APPROVED,
    )
    # The member's own bookings -- what /portal/bookings and the "Coming up"
    # list on the portal home are there to show. Instant-confirm, so approved.
    get_or_create_booking(
        db, room=rooms["OG-202"], party=jane, title="Lesekreis",
        start_at=now + timedelta(days=15, hours=3), end_at=now + timedelta(days=15, hours=6),
        status=BookingStatus.APPROVED,
        source=BookingSource.INTERNAL, created_by=member,
    )
    get_or_create_booking(
        db, room=rooms["EG-102"], party=jane, title="Redaktionssitzung",
        start_at=now + timedelta(days=3, hours=1), end_at=now + timedelta(days=3, hours=4),
        status=BookingStatus.APPROVED,
        source=BookingSource.INTERNAL, created_by=member,
    )
    get_or_create_booking(
        db, room=rooms["AN-01"], party=jane, title="Schreibwerkstatt",
        start_at=now - timedelta(days=9, hours=2), end_at=now - timedelta(days=9),
        status=BookingStatus.COMPLETED,
        source=BookingSource.INTERNAL, created_by=member,
    )

    # A public request, the one the booking detail page was rebuilt around:
    # an external requester, a cleaning quote, extras, and liability cover
    # promised but not yet proven -- the state staff actually have to chase.
    guest = get_or_create_party(
        db, party_type=PartyType.EXTERNAL, name="Black Academy Berlin e. V.",
        email="anfrage@blackacademy.example",
    )
    public_request = get_or_create_booking(
        db, room=rooms["HG-BIB"], party=guest,
        title="Schreibwerkstatt: Afrodiasporische Lyrik",
        # A time a person would actually pick, so the demo reads as a real
        # request rather than "now plus some hours".
        start_at=(now + timedelta(days=21)).replace(hour=8, minute=0, second=0, microsecond=0),
        end_at=(now + timedelta(days=21)).replace(hour=15, minute=0, second=0, microsecond=0),
        status=BookingStatus.PENDING, source=BookingSource.PUBLIC,
    )
    public_request.attendee_count = 25
    public_request.purpose = "Öffentlicher Schreibworkshop mit Lesung"
    if db.scalar(select(BookingRequest).where(BookingRequest.booking_id == public_request.id)) is None:
        db.add(
            BookingRequest(
                booking_id=public_request.id,
                public_ref="RB-DEMO2026",
                language="de",
                requester_first_name="Amara",
                requester_last_name="Okonkwo",
                requester_academic_title="Dr.",
                requester_organization="Black Academy Berlin e. V.",
                requester_email="amara.okonkwo@blackacademy.example",
                requester_phone="+49 30 1234 5678",
                requester_address="Oranienstraße 25\n10999 Berlin",
                contact_person="Kwame Mensah · +49 170 9876543",
                billing_info="Black Academy Berlin e. V.\nOranienstraße 25, 10999 Berlin",
                additional_info=(
                    "Wir bringen eigene Moderationskoffer mit. Der Raum sollte ab 09:00 "
                    "zugänglich sein, damit wir bestuhlen können."
                ),
                # Promised, no certificate yet -- the state the reminder button
                # and the manage-link upload exist for.
                liability_insurance=True,
                cleaning_rate_daily=Decimal("90.00"),
                cleaning_days=1,
                cleaning_charge=Decimal("90.00"),
                currency="EUR",
            )
        )
        db.flush()

    # Internet and utility style metadata
    add_internet(db, room=rooms["EG-102"], medium=InternetMedium.LAN, channel="SW1/PORT-18", provider="NetCom")
    add_internet(db, room=rooms["EG-102"], medium=InternetMedium.WIFI, channel="SSID-CONF", provider="NetCom")
    add_internet(db, room=rooms["EG-103"], medium=InternetMedium.LAN, channel="SW1/PORT-22", provider="NetCom")
    add_internet(db, room=rooms["OG-201"], medium=InternetMedium.FIBER, channel="VLAN-220", provider="FiberCore")
    add_internet(db, room=rooms["AN-01"], medium=InternetMedium.WIFI, channel="SSID-ANNEX", provider="NetCom")

    # Documents
    get_or_create_document(
        db,
        object_key="documents/contracts/L-2026-001.pdf",
        title="Lease Contract L-2026-001",
        document_type=DocumentType.CONTRACT,
        uploader=admin,
        room=rooms["EG-103"],
        lease=lease_1,
    )
    get_or_create_document(
        db,
        object_key="documents/contracts/L-2026-002.pdf",
        title="Lease Contract L-2026-002",
        document_type=DocumentType.CONTRACT,
        uploader=admin,
        room=rooms["OG-201"],
        lease=lease_2,
    )
    get_or_create_document(
        db,
        object_key="documents/floorplans/hq-ground-floor.pdf",
        title="Ground Floor Plan",
        document_type=DocumentType.FLOORPLAN,
        uploader=admin,
        room=rooms["EG-101"],
    )
    get_or_create_document(
        db,
        object_key="documents/handover/eg103-handover.pdf",
        title="EG-103 Handover Protocol",
        document_type=DocumentType.HANDOVER_PROTOCOL,
        uploader=admin,
        room=rooms["EG-103"],
    )

    # Notifications (for visual dropdown/page)
    add_notification(
        db,
        user=admin,
        title="Lease Expiring Soon",
        message="Lease L-2026-002 expires in 20 days.",
        status=NotificationStatus.UNREAD,
    )
    add_notification(
        db,
        user=admin,
        title="Unreturned Keys",
        message="2 keys are currently unreturned for more than 30 days.",
        status=NotificationStatus.UNREAD,
    )
    add_notification(
        db,
        user=admin,
        title="Booking Approved",
        message="Community Workshop in OG-202 has been approved.",
        status=NotificationStatus.READ,
    )

    db.commit()


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed demo data for visual QA")
    parser.add_argument("--reset", action="store_true", help="Delete all existing data before seeding")
    args = parser.parse_args()

    ensure_schema()

    session = get_session_factory()()
    try:
        if args.reset:
            clear_all_data(session)
        seed(session)
        print("Demo data seeded successfully.")
        print("Suggested login in dev mode: admin@example.com / role super_admin via /auth/login")
    finally:
        session.close()


if __name__ == "__main__":
    main()
