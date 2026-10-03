"""Two people must not be able to book the same slot at the same moment.

The guarantee is an ordering -- lock(room), check, insert, commit -- backed by
a PostgreSQL transaction-scoped advisory lock. `SELECT ... FOR UPDATE` cannot
provide it: when no conflicting row exists there is nothing to lock, and that
is precisely the double-booking case.

SQLite cannot exercise a lock it does not have, so the real proof is the
PostgreSQL test, which is skipped unless RMS_TEST_POSTGRES_URL is set. Without
it the concurrency claim is argued but unverified -- say so rather than
assuming the SQLite test covers it.
"""

from __future__ import annotations

import threading
from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest
import sqlalchemy as sa
from sqlalchemy.orm import sessionmaker

from app.models.booking import Booking
from app.models.building import Building
from app.models.enums import BookingSource, BookingStatus, OccupancyMode, PartyType
from app.models.floor import Floor
from app.models.party import Party
from app.models.room import Room
from app.services.bookings import (
    BookingInput,
    RoomUnavailable,
    TimeframeInput,
    create_booking,
)

TZ = ZoneInfo("Europe/Berlin")
START = datetime(2030, 6, 10, 10, 0, tzinfo=TZ)
END = datetime(2030, 6, 10, 12, 0, tzinfo=TZ)


def _seed(session) -> tuple[int, int]:
    building = Building(name="Main")
    session.add(building)
    session.flush()
    floor = Floor(building_id=building.id, name="G", floor_number=0)
    session.add(floor)
    session.flush()
    room = Room(
        floor_id=floor.id, room_code="C-1", name="Contested", usage_type="meeting",
        occupancy_mode=OccupancyMode.BOOKABLE, bookable=True,
        cleaning_rate_daily=Decimal("10.00"),
    )
    party = Party(party_type=PartyType.ORGANIZATION, name="P", is_active=True)
    session.add_all([room, party])
    session.commit()
    return room.id, party.id


def _book(session, room_id: int, party_id: int):
    return create_booking(
        session,
        room=session.get(Room, room_id),
        party=session.get(Party, party_id),
        data=BookingInput(
            room_id=room_id,
            title="Contested slot",
            timeframe=TimeframeInput(start_at=START, end_at=END),
        ),
        source=BookingSource.INTERNAL,
        status=BookingStatus.APPROVED,
    )


def test_second_booking_in_a_fresh_transaction_is_refused(db_session, db_setup):
    """Ordering check on SQLite: proves check-then-insert rejects, not the lock."""
    room_id, party_id = _seed(db_session)
    _book(db_session, room_id, party_id)

    with pytest.raises(RoomUnavailable):
        _book(db_session, room_id, party_id)


def test_concurrent_bookings_yield_exactly_one(postgres_engine):
    """The real proof, on PostgreSQL: two threads race the same slot."""
    Session = sessionmaker(bind=postgres_engine, autocommit=False, autoflush=False)

    with Session() as seed_session:
        room_id, party_id = _seed(seed_session)

    barrier = threading.Barrier(2)
    outcomes: list[str] = []
    lock = threading.Lock()

    def attempt() -> None:
        with Session() as session:
            barrier.wait(timeout=10)
            try:
                _book(session, room_id, party_id)
                result = "booked"
            except RoomUnavailable:
                result = "refused"
            except Exception as exc:  # pragma: no cover - surfaces a real bug
                result = f"error: {exc!r}"
            with lock:
                outcomes.append(result)

    threads = [threading.Thread(target=attempt) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)

    with Session() as session:
        count = session.scalar(
            sa.select(sa.func.count()).select_from(Booking).where(Booking.room_id == room_id)
        )

    assert sorted(outcomes) == ["booked", "refused"], outcomes
    assert count == 1, f"expected exactly one booking, found {count}"
