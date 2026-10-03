Yes. With **Flask + Jinja2 + TailwindCSS + PostgreSQL**, this is a very good fit.

Your decision to start with a **floor-plan-driven UI** is the right one. It gives you:

* a spatial way to navigate the building immediately
* low implementation complexity compared with 3D
* a clean migration path later to SVG → richer SVG → 3D

Flask’s templating model is well suited to server-rendered room detail views and dashboards via Jinja template inheritance, and Flask blueprints are the right way to split the app into room, contract, booking, and admin modules. Flask’s docs also still treat Jinja as the standard rendering path, and blueprints as the modular composition mechanism for larger applications. ([Flask][1])

What matters most now is getting the **domain model** right, because the floor-plan UI will only be a projection of your backend truth.

---

# 1. Recommended architecture

Think of the system in four layers.

## A. Building structure

This is the static physical hierarchy:

* Building
* Floor
* Room

## B. Commercial / occupancy layer

This is who uses what, and under what agreement:

* Tenant or Occupant
* Lease / Rental Contract
* Booking
* Room assignment history

## C. Infrastructure / asset layer

This is what the room contains or is connected to:

* Utility meter
* Internet connection
* Equipment / Ausstattung
* Keys and key handovers
* Documents

## D. UI layer

This is how users access the data:

* Dashboard
* Floor plan
* Room detail view
* Booking calendar
* Contract list
* Alerts / expiries

The critical design rule is:

**Do not model the current state as plain text fields if the thing has a history.**

That applies especially to:

* occupants
* rent
* contracts
* keys
* bookings
* internet assignments, if ports/channels can change

---

# 2. Recommended data model

I would model this around **Room** as the core entity.

Below is the domain model I would actually use.

---

## 2.1 Building

Represents the organization building.

```python
class Building(db.Model):
    __tablename__ = "buildings"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    street = db.Column(db.String(255))
    postal_code = db.Column(db.String(20))
    city = db.Column(db.String(120))
    notes = db.Column(db.Text)

    floors = db.relationship("Floor", back_populates="building", cascade="all, delete-orphan")
```

### Why it exists

Even if you only have one building now, model it explicitly.

That keeps the schema clean and avoids hardcoding “one-building assumptions” into rooms, leases, bookings, and floor plans.

---

## 2.2 Floor

Each building has floors. Each floor can have its own floor plan.

```python
class Floor(db.Model):
    __tablename__ = "floors"

    id = db.Column(db.Integer, primary_key=True)
    building_id = db.Column(db.Integer, db.ForeignKey("buildings.id"), nullable=False)
    name = db.Column(db.String(100), nullable=False)      # e.g. "Ground Floor"
    floor_number = db.Column(db.Integer, nullable=False)  # e.g. 0, 1, 2
    svg_path = db.Column(db.String(255))                  # uploaded SVG file path
    image_path = db.Column(db.String(255))                # optional image fallback
    notes = db.Column(db.Text)

    building = db.relationship("Building", back_populates="floors")
    rooms = db.relationship("Room", back_populates="floor", cascade="all, delete-orphan")
```

### Why both `svg_path` and `image_path`

Because you may initially get:

* SVG exports from CAD
* rasterized floor plans
* PDFs later converted to images/SVG manually

Starting with both prevents your model from becoming dependent on one asset format.

---

## 2.3 Room

This is the central master record.

```python
class Room(db.Model):
    __tablename__ = "rooms"

    id = db.Column(db.Integer, primary_key=True)
    floor_id = db.Column(db.Integer, db.ForeignKey("floors.id"), nullable=False)

    room_code = db.Column(db.String(50), nullable=False, unique=True)   # e.g. "EG-101"
    name = db.Column(db.String(150), nullable=False)                    # e.g. "Seminarraum 1"

    length_m = db.Column(db.Numeric(8, 2))
    width_m = db.Column(db.Numeric(8, 2))
    height_m = db.Column(db.Numeric(8, 2))
    area_sqm = db.Column(db.Numeric(10, 2))

    usage_type = db.Column(db.String(50), nullable=False)  # office, storage, studio, meeting, event, etc.
    occupancy_mode = db.Column(db.String(30), nullable=False)  # leasable, bookable, internal, mixed

    rentable = db.Column(db.Boolean, default=False, nullable=False)
    bookable = db.Column(db.Boolean, default=False, nullable=False)
    active = db.Column(db.Boolean, default=True, nullable=False)

    meter_number = db.Column(db.String(100))
    has_internet = db.Column(db.Boolean, default=False, nullable=False)

    floor = db.relationship("Floor", back_populates="rooms")

    leases = db.relationship("Lease", back_populates="room", cascade="all, delete-orphan")
    bookings = db.relationship("Booking", back_populates="room", cascade="all, delete-orphan")
    key_assignments = db.relationship("KeyAssignment", back_populates="room", cascade="all, delete-orphan")
    room_equipment = db.relationship("RoomEquipment", back_populates="room", cascade="all, delete-orphan")
    internet_connections = db.relationship("InternetConnection", back_populates="room", cascade="all, delete-orphan")
    documents = db.relationship("Document", back_populates="room", cascade="all, delete-orphan")
```

### Important notes

`occupancy_mode` is more important than a simple status.

For example:

* `leasable` → long-term rental logic applies
* `bookable` → short-term booking logic applies
* `mixed` → maybe long-term default but also temporarily reservable
* `internal` → not externally rented

Do **not** store “occupied” as a permanent truth field. That should be **derived** from active leases and active bookings.

---

## 2.4 Tenant / Occupant

You need one entity for the person or organization using the room.

```python
class Party(db.Model):
    __tablename__ = "parties"

    id = db.Column(db.Integer, primary_key=True)
    party_type = db.Column(db.String(20), nullable=False)  # person, organization
    name = db.Column(db.String(255), nullable=False)

    email = db.Column(db.String(255))
    phone = db.Column(db.String(100))

    street = db.Column(db.String(255))
    postal_code = db.Column(db.String(20))
    city = db.Column(db.String(120))

    notes = db.Column(db.Text)

    leases = db.relationship("Lease", back_populates="party")
    bookings = db.relationship("Booking", back_populates="party")
    key_assignments = db.relationship("KeyAssignment", back_populates="party")
```

### Why `Party` and not just `Tenant`

Because some room users are:

* tenants
* internal teams
* temporary event organizers
* partner organizations

`Party` is the more durable abstraction.

---

## 2.5 Lease / Rental Contract

This is the authoritative long-term occupancy record.

```python
class Lease(db.Model):
    __tablename__ = "leases"

    id = db.Column(db.Integer, primary_key=True)
    room_id = db.Column(db.Integer, db.ForeignKey("rooms.id"), nullable=False)
    party_id = db.Column(db.Integer, db.ForeignKey("parties.id"), nullable=False)

    contract_reference = db.Column(db.String(100), unique=True)
    start_date = db.Column(db.Date, nullable=False)
    end_date = db.Column(db.Date)
    notice_period_days = db.Column(db.Integer)

    monthly_rent = db.Column(db.Numeric(10, 2), nullable=False)
    deposit_amount = db.Column(db.Numeric(10, 2))
    currency = db.Column(db.String(3), default="EUR", nullable=False)

    status = db.Column(db.String(30), nullable=False, default="draft")
    # draft, active, expired, terminated, cancelled

    contract_file_path = db.Column(db.String(255))
    notes = db.Column(db.Text)

    room = db.relationship("Room", back_populates="leases")
    party = db.relationship("Party", back_populates="leases")
```

### Why the lease owns rent

Because rent is legally part of the contractual period, not an eternal room property.

If rent changes, you generally want either:

* a new lease
* an amendment
* a rent history table

For MVP, `monthly_rent` on the lease is enough.

### Constraint you should enforce in application logic

For a room with `occupancy_mode="leasable"`, there should not be more than one overlapping active lease for the same date range.

That is business logic, not just UI validation.

---

## 2.6 Booking

For rooms that are short-term reservable.

```python
class Booking(db.Model):
    __tablename__ = "bookings"

    id = db.Column(db.Integer, primary_key=True)
    room_id = db.Column(db.Integer, db.ForeignKey("rooms.id"), nullable=False)
    party_id = db.Column(db.Integer, db.ForeignKey("parties.id"), nullable=False)

    title = db.Column(db.String(255), nullable=False)
    start_at = db.Column(db.DateTime, nullable=False)
    end_at = db.Column(db.DateTime, nullable=False)

    status = db.Column(db.String(30), nullable=False, default="confirmed")
    # tentative, confirmed, cancelled, completed

    purpose = db.Column(db.String(255))
    attendee_count = db.Column(db.Integer)
    notes = db.Column(db.Text)

    room = db.relationship("Room", back_populates="bookings")
    party = db.relationship("Party", back_populates="bookings")
```

### Core booking rules

You need overlap validation:

* same room
* overlapping time range
* only blocking statuses count

For example, two `cancelled` bookings should not block anything, but `confirmed` should.

---

## 2.7 Internet connection

You mentioned “if it has internet, through what channel.”

That deserves a real structure.

```python
class InternetConnection(db.Model):
    __tablename__ = "internet_connections"

    id = db.Column(db.Integer, primary_key=True)
    room_id = db.Column(db.Integer, db.ForeignKey("rooms.id"), nullable=False)

    medium = db.Column(db.String(30), nullable=False)     # lan, wifi, fiber, coax
    channel = db.Column(db.String(100))                   # switch port, VLAN, SSID, patch panel, etc.
    provider = db.Column(db.String(100))
    active = db.Column(db.Boolean, default=True, nullable=False)
    notes = db.Column(db.Text)

    room = db.relationship("Room", back_populates="internet_connections")
```

### Why not just `room.internet_channel`

Because infrastructure changes over time and can become plural.

One room may eventually have:

* Wi-Fi only
* Wi-Fi + wired LAN
* multiple wall ports
* special VLAN or network segment

---

## 2.8 Keys and key handover

Keys must be modeled transactionally.

```python
class Key(db.Model):
    __tablename__ = "keys"

    id = db.Column(db.Integer, primary_key=True)
    key_code = db.Column(db.String(100), nullable=False, unique=True)
    description = db.Column(db.String(255))
    master_key = db.Column(db.Boolean, default=False, nullable=False)
    active = db.Column(db.Boolean, default=True, nullable=False)

    assignments = db.relationship("KeyAssignment", back_populates="key", cascade="all, delete-orphan")
```

```python
class KeyAssignment(db.Model):
    __tablename__ = "key_assignments"

    id = db.Column(db.Integer, primary_key=True)
    key_id = db.Column(db.Integer, db.ForeignKey("keys.id"), nullable=False)
    room_id = db.Column(db.Integer, db.ForeignKey("rooms.id"), nullable=False)
    party_id = db.Column(db.Integer, db.ForeignKey("parties.id"), nullable=False)

    issued_at = db.Column(db.DateTime, nullable=False)
    returned_at = db.Column(db.DateTime)
    issue_note = db.Column(db.Text)
    return_note = db.Column(db.Text)

    key = db.relationship("Key", back_populates="assignments")
    room = db.relationship("Room", back_populates="key_assignments")
    party = db.relationship("Party", back_populates="key_assignments")
```

### Why this matters

This gives you:

* who has which key now
* who had it before
* whether it was returned
* room-level and tenant-level auditability

That is much stronger than a text field like “received 2 keys”.

---

## 2.9 Ausstattung / equipment

This should be many-to-many, because equipment definitions and room quantities are separate concerns.

```python
class Equipment(db.Model):
    __tablename__ = "equipment"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(150), nullable=False, unique=True)   # Projector, Desk, Sink, etc.
    category = db.Column(db.String(100))
    notes = db.Column(db.Text)

    room_links = db.relationship("RoomEquipment", back_populates="equipment")
```

```python
class RoomEquipment(db.Model):
    __tablename__ = "room_equipment"

    id = db.Column(db.Integer, primary_key=True)
    room_id = db.Column(db.Integer, db.ForeignKey("rooms.id"), nullable=False)
    equipment_id = db.Column(db.Integer, db.ForeignKey("equipment.id"), nullable=False)

    quantity = db.Column(db.Integer, nullable=False, default=1)
    fixed = db.Column(db.Boolean, default=True, nullable=False)
    notes = db.Column(db.Text)

    room = db.relationship("Room", back_populates="room_equipment")
    equipment = db.relationship("Equipment", back_populates="room_links")
```

### Why this pattern

Because “whiteboard” or “desk” should be reusable reference data, while room-specific quantity and notes belong in the association table.

This is exactly the kind of many-to-many relationship SQLAlchemy’s ORM relationship system is designed to support. SQLAlchemy’s current relationship documentation still treats association patterns like this as standard ORM practice. ([SQLAlchemy Documentation][2])

---

## 2.10 Documents

A room management system without document support becomes painful quickly.

```python
class Document(db.Model):
    __tablename__ = "documents"

    id = db.Column(db.Integer, primary_key=True)
    room_id = db.Column(db.Integer, db.ForeignKey("rooms.id"))
    lease_id = db.Column(db.Integer, db.ForeignKey("leases.id"))

    document_type = db.Column(db.String(50), nullable=False)
    # contract, floorplan, handover_protocol, invoice, photo, inspection, other

    title = db.Column(db.String(255), nullable=False)
    file_path = db.Column(db.String(255), nullable=False)
    uploaded_at = db.Column(db.DateTime, nullable=False)
    notes = db.Column(db.Text)

    room = db.relationship("Room", back_populates="documents")
```

### Design note

You may later want a more generic `document_links` table so one document can attach to many entities, but for MVP this is enough.

---

# 3. Derived state you should compute, not store

This is a major architectural point.

A room detail page will show fields like:

* currently occupied by
* monthly rent
* lease expires on
* currently booked?
* next booking
* active keys
* internet available

Some of these should be stored directly. Some should be derived.

## Store directly

* dimensions
* room code
* meter number
* rentable/bookable flags
* base equipment
* internet connection records

## Derive dynamically

* current occupant
* current monthly rent
* current active contract
* rent expiry
* next booking
* room availability right now
* currently issued keys

For example:

```python
from datetime import date, datetime
from sqlalchemy import select, and_

def get_active_lease(room_id: int):
    today = date.today()

    stmt = (
        select(Lease)
        .where(
            Lease.room_id == room_id,
            Lease.status == "active",
            Lease.start_date <= today,
            db.or_(Lease.end_date.is_(None), Lease.end_date >= today),
        )
        .order_by(Lease.start_date.desc())
    )
    return db.session.execute(stmt).scalars().first()
```

### Why `select(...)` style

Because Flask-SQLAlchemy explicitly notes that the legacy `Model.query` / `session.query` style is considered legacy through SQLAlchemy’s current direction, and the modern `select(...)`-based pattern is preferred. ([Flask-SQLAlchemy Documentation][3])

That matters because if you start cleanly now, your codebase will age much better.

---

# 4. The SVG floor-plan approach

This is the right UI starting point.

The best pattern is:

1. each floor has an SVG file
2. each room polygon/path/group has a stable identifier
3. the SVG element carries the backend room ID or room code
4. clicking a room opens `/rooms/<id>` or loads a side panel

MDN still documents SVG `<a>` and related SVG elements as first-class clickable/interactive constructs in modern browsers, so building floor-plan interactivity on top of SVG is fully normal web-platform behavior. ([MDN Web Docs][4])

## Example SVG structure

```xml
<svg viewBox="0 0 1200 800" xmlns="http://www.w3.org/2000/svg">
  <a href="/rooms/12" class="room-link">
    <rect id="room-EG-101" data-room-code="EG-101" x="120" y="140" width="220" height="160" />
    <text x="150" y="220">EG-101</text>
  </a>

  <a href="/rooms/13" class="room-link">
    <rect id="room-EG-102" data-room-code="EG-102" x="360" y="140" width="200" height="160" />
    <text x="390" y="220">EG-102</text>
  </a>
</svg>
```

### Better pattern than hardcoding links into the source SVG

Often better is:

* store room shapes with IDs in SVG
* inject status classes server-side or client-side

For example, the SVG has:

```xml
<rect id="room-shape-EG-101" data-room-code="EG-101" ... />
```

Then in Jinja:

```html
<script>
  const roomMap = {{ room_status_map|tojson }};
</script>
```

And JS adds classes like:

* `is-free`
* `is-occupied`
* `is-booked-today`
* `expires-soon`

This avoids duplicating SVG files every time room state changes.

---

# 5. How I would structure the Flask app

Use blueprints from the beginning.

```text
app/
├── __init__.py
├── extensions.py
├── models/
│   ├── __init__.py
│   ├── building.py
│   ├── room.py
│   ├── lease.py
│   ├── booking.py
│   ├── key.py
│   └── document.py
├── blueprints/
│   ├── main/
│   ├── rooms/
│   ├── floors/
│   ├── leases/
│   ├── bookings/
│   ├── parties/
│   └── admin/
├── services/
│   ├── occupancy_service.py
│   ├── booking_service.py
│   ├── key_service.py
│   └── floorplan_service.py
├── templates/
│   ├── base.html
│   ├── rooms/
│   ├── floors/
│   ├── leases/
│   └── bookings/
├── static/
│   ├── css/
│   ├── js/
│   ├── uploads/
│   │   ├── floorplans/
│   │   └── documents/
│   └── svg/
└── forms/
    ├── room_forms.py
    ├── lease_forms.py
    └── booking_forms.py
```

### Why `services/`

Because business logic should not live in routes.

Bad:

* route queries a room
* route manually figures out active lease
* route manually checks bookings
* route assembles UI state

Good:

* route calls `room_detail_service.get_room_view_model(room_id)`
* service returns a normalized room-detail object

This matters a lot once you have multiple screens needing the same business truth.

---

# 6. Core screens for MVP

## A. Dashboard

Shows:

* total rooms
* occupied rooms
* free leasable rooms
* rooms with expiring leases
* rooms booked today
* overdue key returns if you add that later

## B. Building view

A list of floors.

## C. Floor plan view

Displays the floor SVG with room overlays.

Each room card/tooltip shows:

* room code
* room name
* current status
* occupant if any
* next booking if bookable

## D. Room detail page

This is the most important screen.

Suggested sections:

1. header

   * room code, room name, floor, usage type

2. physical data

   * dimensions, area, meter number

3. occupancy

   * current tenant, contract dates, monthly rent, expiry

4. booking

   * current booking state, next booking, calendar link

5. internet

   * available? medium? channel?

6. keys

   * active assignments, issued/returned

7. equipment

   * list and quantities

8. documents

   * contract PDFs, photos, handover forms, floor plan extract

## E. Lease list

Search/filter by:

* active
* expiring in 30/60/90 days
* expired
* room
* tenant

## F. Booking calendar

For bookable rooms only.

---

# 7. Important business rules

These should be explicit in code.

## Rule 1: leasable rooms cannot have overlapping active leases

This is your occupancy integrity rule.

## Rule 2: bookable rooms cannot have overlapping confirmed bookings

This is your scheduling integrity rule.

## Rule 3: internal-only rooms should reject lease creation

If `occupancy_mode = internal`, lease creation should fail.

## Rule 4: key assignment should require an active party

No anonymous key handovers.

## Rule 5: contract end date alerts should be computed ahead of time

Examples:

* expires in 90 days
* expires in 30 days
* expires in 7 days
* expired

## Rule 6: room status is computed from multiple signals

For example:

* leased and active → occupied
* no lease, future booking only → free until booking
* current booking active → booked now
* inactive room → unavailable
* maintenance flag later → unavailable/maintenance

You can encode this into a service method.

---

# 8. Suggested enums / controlled vocabularies

Do not leave everything as free text forever.

Use constrained values for things like:

* `usage_type`
* `occupancy_mode`
* `lease.status`
* `booking.status`
* `internet.medium`
* `document_type`

This improves:

* filtering
* reporting
* validation
* consistency in Jinja templates

For MVP, simple strings with app-level validation are okay. Later you can move toward Python enums or DB enums.

---

# 9. Example room detail query shape

For the room detail page, your route should not perform 15 separate template queries.

Instead, assemble a room view model in one service.

```python
def build_room_detail(room_id: int) -> dict:
    room = db.session.get(Room, room_id)
    if not room:
        raise LookupError("Room not found")

    active_lease = get_active_lease(room_id)
    next_booking = get_next_booking(room_id)
    active_keys = get_active_key_assignments(room_id)

    return {
        "room": room,
        "active_lease": active_lease,
        "next_booking": next_booking,
        "active_keys": active_keys,
        "equipment": room.room_equipment,
        "internet_connections": room.internet_connections,
        "documents": room.documents,
        "computed_status": compute_room_status(room, active_lease, next_booking),
    }
```

That keeps your Jinja templates simple.

Flask’s template system is explicitly built around standard Jinja rendering and template inheritance, so this server-rendered approach is aligned with how Flask expects larger template sets to be structured. ([Flask][1])

---

# 10. Example Jinja-driven floor view

```html
{% extends "base.html" %}

{% block content %}
<div class="space-y-6">
  <header>
    <h1 class="text-2xl font-semibold">{{ floor.name }}</h1>
    <p class="text-sm text-slate-600">{{ floor.building.name }}</p>
  </header>

  <div class="rounded-2xl border bg-white p-4 shadow-sm overflow-auto">
    {{ svg_content|safe }}
  </div>

  <div class="grid gap-4 md:grid-cols-3">
    {% for room in rooms %}
      <a href="{{ url_for('rooms.detail', room_id=room.id) }}"
         class="rounded-xl border p-4 hover:bg-slate-50">
        <div class="font-medium">{{ room.room_code }} — {{ room.name }}</div>
        <div class="text-sm text-slate-600">{{ room.usage_type }}</div>
      </a>
    {% endfor %}
  </div>
</div>
{% endblock %}
```

### Security caveat

Only render `svg_content|safe` if the SVG source is trusted or sanitized.

Because once you mark content safe, you bypass escaping. Flask’s docs emphasize that Jinja autoescaping is there to protect rendered HTML, so you should treat uploaded SVGs as active content, not inert images. ([Flask][5])

This is an important security point.

---

# 11. Storage decisions

## Database

Use PostgreSQL.

Reason:

* date range logic
* better integrity
* future reporting
* easier scaling than SQLite
* later potential for exclusion constraints if you want stronger booking validation

## File storage

For now:

* local file storage is acceptable for floor plans and contracts

Later:

* S3-compatible object storage is better

Store in DB only:

* path
* original filename
* type
* timestamp
* owner entity

Do not store raw PDFs in the relational DB unless there is a specific compliance reason.

---

# 12. Development sequence I would follow

## Phase 1

* buildings
* floors
* rooms
* static floor-plan upload
* room detail page

At this stage, clicking on a room in a floor plan should already work.

## Phase 2

* parties
* leases
* contract upload
* computed occupancy state
* room detail occupancy section

## Phase 3

* keys
* equipment
* internet metadata
* document center

## Phase 4

* bookings
* next booking logic
* room availability status
* calendar

## Phase 5

* alerts
* expiring leases
* expiring bookings
* unreturned keys
* reporting/export

This sequence reduces risk because the floor plan becomes useful early, before the entire commercial layer is finished.

---

# 13. What I would not do yet

I would avoid these in the first version:

* full 3D viewer
* real-time notifications
* complex invoicing
* accounting integration
* maintenance workflow
* role-granular per-field permissions
* BIM import complexity

Those are all valid later, but they are not the shortest path to a durable operational system.

---

# 14. My concrete recommendation for your stack

For your exact setup, I would choose:

* **Flask**
* **Flask-SQLAlchemy**
* **Alembic / Flask-Migrate**
* **PostgreSQL**
* **Jinja2**
* **TailwindCSS**
* **WTForms or Flask-WTF**
* **simple vanilla JS for SVG interaction**
* optional **HTMX later** for partial page refreshes if you want smoother UI without a SPA

And I would model the backend around these first-class entities:

* `Building`
* `Floor`
* `Room`
* `Party`
* `Lease`
* `Booking`
* `Key`
* `KeyAssignment`
* `Equipment`
* `RoomEquipment`
* `InternetConnection`
* `Document`

That gives you a clean operational core.

---
