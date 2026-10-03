"""Unit tests for the booking service -- no HTTP, no fixtures beyond a Session.

Several cases here exist specifically because the Flask app this feature
replaces got them wrong. Those are marked in the docstrings.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest

from app.models.booking import Booking
from app.models.booking_service import BookingService
from app.models.building import Building
from app.models.enums import (
    BookingSource,
    BookingStatus,
    LeaseStatus,
    OccupancyMode,
    PartyType,
)
from app.models.equipment import Equipment, RoomEquipment
from app.models.floor import Floor
from app.models.internal_room_assignment import InternalRoomAssignment
from app.models.lease import Lease
from app.models.party import Party
from app.models.room import Room
from app.services.bookings import (
    BookingError,
    BookingInput,
    EquipmentLine,
    PublicRequesterInput,
    RoomUnavailable,
    ServiceLine,
    TimeframeInput,
    compute_cleaning_charge,
    create_booking,
    find_conflicts,
    normalize_timeframe,
    resolve_public_requester,
)

TZ = ZoneInfo("Europe/Berlin")


def _dt(day: int, hour: int = 0, minute: int = 0, *, month: int = 6, year: int = 2030) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=TZ)


@pytest.fixture
def room(db_session):
    building = Building(name="Main")
    db_session.add(building)
    db_session.flush()
    floor = Floor(building_id=building.id, name="Ground", floor_number=0)
    db_session.add(floor)
    db_session.flush()
    room = Room(
        floor_id=floor.id,
        room_code="G-1",
        name="Main Hall",
        usage_type="meeting",
        occupancy_mode=OccupancyMode.BOOKABLE,
        bookable=True,
        public_bookable=True,
        capacity=50,
        cleaning_rate_daily=Decimal("45.00"),
    )
    db_session.add(room)
    db_session.commit()
    return room


@pytest.fixture
def party(db_session):
    party = Party(party_type=PartyType.ORGANIZATION, name="Tenant A", is_active=True)
    db_session.add(party)
    db_session.commit()
    return party


def _approved(db_session, room, party, start, end):
    booking = Booking(
        room_id=room.id,
        party_id=party.id,
        title="Existing",
        start_at=start,
        end_at=end,
        status=BookingStatus.APPROVED,
        source=BookingSource.STAFF,
    )
    db_session.add(booking)
    db_session.commit()
    return booking


def _input(room, start, end, **kwargs) -> BookingInput:
    kwargs.setdefault("title", "Test event")
    return BookingInput(
        room_id=room.id,
        timeframe=TimeframeInput(start_at=start, end_at=end, whole_day=kwargs.pop("whole_day", False)),
        **kwargs,
    )


# --------------------------------------------------------------------------
# Conflict semantics
# --------------------------------------------------------------------------


def test_touching_bookings_do_not_conflict(db_session, room, party):
    """Half-open: back-to-back slots are legal.

    The reference app rejected these -- its check used `end_time >= start_time`,
    so 09:00-11:00 blocked 11:00-13:00 and consecutive bookings were impossible.
    """
    _approved(db_session, room, party, _dt(10, 10), _dt(10, 11))
    conflicts = find_conflicts(db_session, room_id=room.id, start_at=_dt(10, 11), end_at=_dt(10, 12))
    assert conflicts == []


def test_overlapping_bookings_conflict(db_session, room, party):
    _approved(db_session, room, party, _dt(10, 10), _dt(10, 12))
    conflicts = find_conflicts(db_session, room_id=room.id, start_at=_dt(10, 11), end_at=_dt(10, 13))
    assert [c["kind"] for c in conflicts] == ["booking"]


def test_overnight_booking_conflict_is_detected(db_session, room, party):
    """The defect that made the reference app double-book rooms.

    It compared date ranges and clock-time ranges as two independent
    one-dimensional overlaps. For Mon 22:00 -> Tue 02:00 against Tue 01:00 ->
    03:00 the date ranges overlap but the clock windows [22:00, 02:00] and
    [01:00, 03:00] do not, so it accepted the second booking and let two
    parties into the room at once.
    """
    _approved(db_session, room, party, _dt(10, 22), _dt(11, 2))
    conflicts = find_conflicts(db_session, room_id=room.id, start_at=_dt(11, 1), end_at=_dt(11, 3))
    assert [c["kind"] for c in conflicts] == ["booking"]


@pytest.mark.parametrize(
    "status,blocks",
    [
        (BookingStatus.APPROVED, True),
        (BookingStatus.PENDING, False),
        (BookingStatus.REJECTED, False),
        (BookingStatus.CANCELLED, False),
        (BookingStatus.COMPLETED, False),
    ],
)
def test_only_approved_bookings_block(db_session, room, party, status, blocks):
    """A pending public request is a request, not a reservation."""
    db_session.add(
        Booking(
            room_id=room.id,
            party_id=party.id,
            title="Other",
            start_at=_dt(10, 10),
            end_at=_dt(10, 12),
            status=status,
            source=BookingSource.PUBLIC,
        )
    )
    db_session.commit()
    conflicts = find_conflicts(db_session, room_id=room.id, start_at=_dt(10, 11), end_at=_dt(10, 13))
    assert bool(conflicts) is blocks


def test_active_lease_blocks_booking(db_session, room, party):
    """Without this a member could instant-confirm a room let to a tenant."""
    db_session.add(
        Lease(
            room_id=room.id,
            party_id=party.id,
            contract_reference="L-1",
            start_date=date(2030, 1, 1),
            end_date=date(2030, 12, 31),
            monthly_rent=Decimal("100.00"),
            status=LeaseStatus.ACTIVE,
        )
    )
    db_session.commit()
    conflicts = find_conflicts(db_session, room_id=room.id, start_at=_dt(10, 10), end_at=_dt(10, 12))
    assert [c["kind"] for c in conflicts] == ["lease"]


def test_internal_assignment_blocks_public_but_not_internal_on_mixed(db_session, room, party):
    """A mixed room hosts bookings alongside its resident team -- that is the point.

    The public audience is still refused: an outside group should not be sold a
    room a team is sitting in.
    """
    room.occupancy_mode = OccupancyMode.MIXED
    team = Party(party_type=PartyType.TEAM, name="Team A", is_active=True)
    db_session.add(team)
    db_session.flush()
    db_session.add(
        InternalRoomAssignment(room_id=room.id, party_id=team.id, start_date=date(2030, 1, 1))
    )
    db_session.commit()

    public = find_conflicts(
        db_session, room_id=room.id, start_at=_dt(10, 10), end_at=_dt(10, 12),
        source=BookingSource.PUBLIC,
    )
    internal = find_conflicts(
        db_session, room_id=room.id, start_at=_dt(10, 10), end_at=_dt(10, 12),
        source=BookingSource.INTERNAL,
    )
    assert [c["kind"] for c in public] == ["internal_assignment"]
    assert internal == []


# --------------------------------------------------------------------------
# Timeframe
# --------------------------------------------------------------------------


def test_whole_day_runs_to_midnight_of_the_following_day():
    """Not 23:59:59, which leaves a gap and makes consecutive days collide."""
    start, end = normalize_timeframe(
        TimeframeInput(start_at=_dt(10, 9), end_at=_dt(10, 17), whole_day=True)
    )
    assert start == _dt(10, 0)
    assert end == _dt(11, 0)


def test_consecutive_whole_day_bookings_do_not_collide(db_session, room, party):
    first_start, first_end = normalize_timeframe(
        TimeframeInput(start_at=_dt(10), end_at=_dt(10), whole_day=True)
    )
    _approved(db_session, room, party, first_start, first_end)
    second_start, second_end = normalize_timeframe(
        TimeframeInput(start_at=_dt(11), end_at=_dt(11), whole_day=True)
    )
    assert find_conflicts(db_session, room_id=room.id, start_at=second_start, end_at=second_end) == []


# --------------------------------------------------------------------------
# Cleaning charge
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "start,end,expected_days",
    [
        (_dt(10, 9), _dt(10, 17), 1),
        (_dt(10, 9), _dt(12, 17), 3),
        (_dt(10, 0), _dt(11, 0), 1),  # exactly one whole day, half-open
        (_dt(10, 0), _dt(12, 0), 2),
    ],
)
def test_cleaning_days(room, start, end, expected_days):
    _, days, charge = compute_cleaning_charge(room, start, end)
    assert days == expected_days
    assert charge == Decimal("45.00") * expected_days


def test_cleaning_charge_is_null_when_room_has_no_rate(room):
    room.cleaning_rate_daily = None
    assert compute_cleaning_charge(room, _dt(10, 9), _dt(10, 17)) == (None, None, None)


def test_cleaning_charge_rounds_to_two_places(room):
    room.cleaning_rate_daily = Decimal("33.335")
    _, _, charge = compute_cleaning_charge(room, _dt(10, 9), _dt(10, 17))
    assert charge == Decimal("33.34")


def test_cleaning_charge_ignores_any_client_supplied_value(db_session, room, party):
    """BookingInput has no cleaning_charge field, so a forged price cannot arrive.

    The reference app computed this in the browser and wrote the posted value
    straight to the database.
    """
    assert not hasattr(BookingInput, "cleaning_charge")
    booking = create_booking(
        db_session, room=room, party=party,
        data=_input(room, _dt(10, 9), _dt(10, 17)),
        source=BookingSource.STAFF, status=BookingStatus.PENDING,
    )
    assert booking.request.cleaning_charge == Decimal("45.00")


# --------------------------------------------------------------------------
# Validation
# --------------------------------------------------------------------------


def test_end_before_start_rejected(db_session, room, party):
    with pytest.raises(BookingError) as exc:
        create_booking(
            db_session, room=room, party=party,
            data=_input(room, _dt(10, 12), _dt(10, 10)),
            source=BookingSource.STAFF, status=BookingStatus.PENDING,
        )
    assert exc.value.code == "end_before_start"


def test_booking_in_the_past_rejected(db_session, room, party):
    with pytest.raises(BookingError) as exc:
        create_booking(
            db_session, room=room, party=party,
            data=_input(room, _dt(10, 10, year=2020), _dt(10, 12, year=2020)),
            source=BookingSource.STAFF, status=BookingStatus.PENDING,
        )
    assert exc.value.code == "in_the_past"


def test_over_capacity_rejected(db_session, room, party):
    with pytest.raises(BookingError) as exc:
        create_booking(
            db_session, room=room, party=party,
            data=_input(room, _dt(10, 10), _dt(10, 12), attendee_count=500),
            source=BookingSource.STAFF, status=BookingStatus.PENDING,
        )
    assert exc.value.code == "over_capacity"


def test_public_booking_refused_on_non_public_room(db_session, room, party):
    room.public_bookable = False
    db_session.commit()
    with pytest.raises(BookingError) as exc:
        create_booking(
            db_session, room=room, party=party,
            data=_input(room, _dt(10, 10), _dt(10, 12)),
            source=BookingSource.PUBLIC, status=BookingStatus.PENDING,
        )
    assert exc.value.code == "room_not_public"


def test_equipment_must_belong_to_the_room(db_session, room, party):
    other = Equipment(name="Projector")
    db_session.add(other)
    db_session.commit()
    with pytest.raises(BookingError) as exc:
        create_booking(
            db_session, room=room, party=party,
            data=_input(room, _dt(10, 10), _dt(10, 12), equipment=[EquipmentLine(other.id, 1)]),
            source=BookingSource.STAFF, status=BookingStatus.PENDING,
        )
    assert exc.value.code == "equipment_unknown"


def test_equipment_quantity_capped_by_room_stock(db_session, room, party):
    equipment = Equipment(name="Microphone")
    db_session.add(equipment)
    db_session.flush()
    db_session.add(RoomEquipment(room_id=room.id, equipment_id=equipment.id, quantity=2))
    db_session.commit()
    with pytest.raises(BookingError) as exc:
        create_booking(
            db_session, room=room, party=party,
            data=_input(room, _dt(10, 10), _dt(10, 12), equipment=[EquipmentLine(equipment.id, 5)]),
            source=BookingSource.STAFF, status=BookingStatus.PENDING,
        )
    assert exc.value.code == "equipment_quantity"


def test_inactive_service_rejected(db_session, room, party):
    service = BookingService(code="retired", name="Retired", is_active=False)
    db_session.add(service)
    db_session.commit()
    with pytest.raises(BookingError) as exc:
        create_booking(
            db_session, room=room, party=party,
            data=_input(room, _dt(10, 10), _dt(10, 12), services=[ServiceLine(service.id)]),
            source=BookingSource.STAFF, status=BookingStatus.PENDING,
        )
    assert exc.value.code == "service_unknown"


# --------------------------------------------------------------------------
# Creation
# --------------------------------------------------------------------------


def test_create_booking_writes_request_and_line_items(db_session, room, party):
    equipment = Equipment(name="Flipchart")
    service = BookingService(code="tech", name="Technician")
    db_session.add_all([equipment, service])
    db_session.flush()
    db_session.add(RoomEquipment(room_id=room.id, equipment_id=equipment.id, quantity=4))
    db_session.commit()

    booking = create_booking(
        db_session, room=room, party=party,
        data=_input(
            room, _dt(10, 9), _dt(10, 17),
            equipment=[EquipmentLine(equipment.id, 2)],
            services=[ServiceLine(service.id)],
        ),
        source=BookingSource.PUBLIC, status=BookingStatus.PENDING,
    )

    assert booking.status == BookingStatus.PENDING
    assert booking.source == BookingSource.PUBLIC
    assert booking.request.public_ref.startswith("RB-")
    assert len(booking.equipment_requests) == 1
    assert booking.equipment_requests[0].quantity == 2
    assert len(booking.service_requests) == 1


def test_instant_confirm_refused_when_room_taken(db_session, room, party):
    _approved(db_session, room, party, _dt(10, 10), _dt(10, 12))
    with pytest.raises(RoomUnavailable) as exc:
        create_booking(
            db_session, room=room, party=party,
            data=_input(room, _dt(10, 11), _dt(10, 13)),
            source=BookingSource.INTERNAL, status=BookingStatus.APPROVED,
        )
    assert exc.value.code == "room_unavailable"
    assert exc.value.conflicts and exc.value.conflicts[0]["kind"] == "booking"


def test_public_ref_collision_retries(db_session, room, party, monkeypatch):
    """A duplicate reference must not surface as a 500 with the booking lost."""
    import app.services.bookings as svc

    first = create_booking(
        db_session, room=room, party=party,
        data=_input(room, _dt(10, 9), _dt(10, 10)),
        source=BookingSource.STAFF, status=BookingStatus.PENDING,
    )
    collided = first.request.public_ref
    values = iter([collided, "RB-UNIQUE01", "RB-UNIQUE02"])
    monkeypatch.setattr(svc, "generate_public_ref", lambda: next(values))

    second = create_booking(
        db_session, room=room, party=party,
        data=_input(room, _dt(11, 9), _dt(11, 10)),
        source=BookingSource.STAFF, status=BookingStatus.PENDING,
    )
    assert second.request.public_ref == "RB-UNIQUE01"


# --------------------------------------------------------------------------
# Party resolution
# --------------------------------------------------------------------------


def test_public_requester_never_matches_a_staff_party(db_session):
    """The worst failure available here: a stranger's booking filed against a
    real person's record, silently."""
    staff = Party(party_type=PartyType.PERSON, name="Real Person", email="shared@example.com")
    db_session.add(staff)
    db_session.commit()

    resolved = resolve_public_requester(
        db_session, PublicRequesterInput(email="shared@example.com", first_name="Someone", last_name="Else")
    )
    assert resolved.id != staff.id
    assert resolved.party_type == PartyType.EXTERNAL


def test_public_requester_reuses_the_same_external_party(db_session):
    first = resolve_public_requester(db_session, PublicRequesterInput(email="a@example.com", first_name="A"))
    db_session.commit()
    second = resolve_public_requester(db_session, PublicRequesterInput(email="A@Example.com", first_name="A"))
    assert first.id == second.id
