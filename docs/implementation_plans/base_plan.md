Yes — this is very achievable, and the scope is sensible if you build it in layers.

What you are describing is really **three systems combined into one**:

1. **Room registry / property operations**
   Each room has master data: dimensions, floor, meter number, internet availability, internet channel, Ausstattung, keys, documents, and whether it is rentable or bookable.

2. **Occupancy + contract management**
   Who occupies the room, monthly rent, start/end dates, notice periods, uploaded contract, key handover history, and renewal/expiry alerts.

3. **Spatial interface**
   A floor-plan or 3D building model where each room is clickable and acts as the entry point into the room’s data.

That architecture is common in facilities/property systems, even if most off-the-shelf products split it across separate modules. Browser-based BIM/IFC tooling is mature enough now that clickable 3D building views in a web app are practical, especially with IFC-focused libraries and viewers such as That Open’s web-ifc stack and xeokit. ([GitHub][1])

## How achievable it is

**A strong MVP is very achievable.**
A first production version with room records, contracts, tenant data, keys, booking calendar, expiry reminders, and a **2D floor plan or simple 3D click-through** is well within reach for a custom web app.

**The 3D part is achievable, but it changes the project class.**
The management system itself is standard CRUD + documents + calendar logic. The 3D layer is the only part that meaningfully increases complexity. If you already have architectural drawings, CAD files, or an IFC model, the difficulty drops a lot. If you have nothing but rough measurements, then someone will first need to produce a structured floor plan or BIM-like model.

So the real complexity is:

* **Low to moderate**: room management, leases, keys, documents, reminders
* **Moderate**: booking logic, overlap detection, occupancy timelines
* **Moderate to high**: interactive 3D building model
* **High** only if you want full BIM-grade editing, live IoT integration, or digital-twin behavior

## Best way to think about the data model

Treat **Room** as the core entity, then connect everything else to it.

### Core entities

* **Building**
* **Floor**
* **Room**
* **Tenant / Occupant / Organization**
* **Lease / RentalContract**
* **Booking**
* **Key / KeyAssignment**
* **UtilityMeter**
* **InternetConnection**
* **Equipment / Ausstattung**
* **Document**
* **MaintenanceIssue** later, if needed

### Example room schema

A room record would typically hold:

* room number / internal ID
* room name
* building + floor
* length, width, height
* area in m²
* volume in m³ if relevant
* rentable vs bookable vs internal-use-only
* Stromzähler number
* internet available: yes/no
* internet type/channel: LAN, Wi-Fi, VLAN, switch port, provider line, etc.
* Ausstattung: desks, projector, sink, storage, whiteboard, chairs, AC, accessibility, etc.
* occupancy status
* current tenant
* current monthly rent
* lease start/end
* next booking
* list of issued keys
* attached files: contract, Übergabeprotokoll, floor image, inspection docs

The important design decision is this:

**Do not store “current state” only. Store history.**

For example:

* keys should be tracked through a `key_assignments` table, not a single text field
* rent should be versioned through contracts or amendments
* occupancy should be derived from lease/booking records
* internet assignment should be separately trackable if ports or VLANs change

That makes the system auditable and much easier to trust later.

## 2D first vs 3D first

I would strongly recommend this sequence:

### Option A — 2D-first

Start with:

* normal admin app
* room list
* floor overview
* clickable SVG or image-based floor plans

This gives almost all the business value quickly.

### Option B — 3D later

Once the data model is stable, add:

* IFC or glTF model viewer
* click room in 3D
* highlight occupied/booked/expiring rooms
* open room detail drawer

This is usually the smarter route because the data model is the hard business core. The 3D layer is mainly a navigation and visualization layer on top of that.

## Technology options

### Best custom-stack route

Given your usual direction, I would build it as:

* **Backend**: Flask or FastAPI
* **DB**: PostgreSQL
* **Frontend**: React / Next.js
* **Documents**: object storage or local file storage with metadata in DB
* **Calendar/booking**: FullCalendar or similar frontend component
* **Auth**: organization SSO or local RBAC
* **3D**: IFC viewer / BIM viewer in browser
* **2D fallback**: SVG floor plans

### Why this stack makes sense

Because this is mostly a **data integrity and workflow system**, not a graphics product. The backend needs to enforce:

* booking overlap rules
* one-active-lease logic
* room state transitions
* role-based access
* document access control
* renewal and expiry notifications

The frontend then becomes a control surface over that logic.

## Tools you can use for the spatial/3D side

### 1. That Open / web-ifc

That Open’s `web-ifc` ecosystem is designed for loading and interacting with IFC models in the browser, and their docs explicitly position it for web-based BIM applications. ([GitHub][1])

Use it if:

* you can get an IFC file from an architect
* you want room-level picking and metadata
* you want a modern browser-native BIM route

### 2. xeokit

xeokit is a mature open-source BIM viewer SDK focused on performance and AEC-style viewing, with support for building model navigation and overlays. Their documentation and examples show floor/storey navigation and 2D-overlay concepts that fit your use case well. ([xeokit.io][2])

Use it if:

* the model could get large
* you want fast viewer performance
* you want a viewer-oriented approach rather than modeling from scratch

### 3. Plain Three.js + glTF

If you do not need BIM semantics and just want “clickable rooms in 3D,” a simpler route is:

* model building in Blender / SketchUp / CAD
* export glTF
* render with Three.js
* map room IDs to meshes

This is simpler than IFC/BIM, but you lose standardized building semantics unless you re-create them yourself.

## Tools for booking and room usage logic

If some rooms are short-term bookable rather than leased, this is normal calendar/resource-booking logic. Open-source room-booking systems like Classroom Bookings and Seatsurfing show that this part is straightforward and well understood in web-app form. ([GitHub][3])

But I would not bolt on a separate booking product unless you want a quick temporary solution. Since your rooms also need leases, contracts, keys, and infrastructure metadata, a **single integrated data model** is cleaner.

## Tools for asset and key tracking

For keys and room equipment, the conceptual model is closer to asset tracking than pure property management. Platforms like Shelf show the pattern: inventory items, assignments, custody, and audit trail. ([GitHub][4])

In your case:

* keys = controlled assignable assets
* Ausstattung = either room-fixed equipment or movable assets
* handover events = logged transactions with date, issuer, recipient, and return status

## Recommended product strategy

I would not start by looking for one giant off-the-shelf product. Your requirements cross:

* lease management
* room booking
* facility inventory
* document storage
* spatial UI / digital floor plan

Most ready-made tools will do one or two of these well and the rest poorly.

### Best practical route

Build it in phases:

#### Phase 1 — operational core

* buildings/floors/rooms
* tenants
* contracts
* rent amounts
* expiry dates
* key assignments
* equipment
* documents
* search/filter/export

#### Phase 2 — booking

* bookable room flag
* booking calendar
* conflict detection
* “next booking” logic
* room availability view

#### Phase 3 — visual layer

* 2D clickable floor plans first
* 3D viewer second

#### Phase 4 — automation

* expiry reminders
* unpaid rent flags
* contract renewal workflow
* key return checklist
* room turnover checklist
* maintenance tickets

## What the 3D model should actually do

Do not think of the 3D model as “the system.” It should be a **navigation surface** over the underlying database.

Clicking a room should reveal:

* room name / number
* dimensions
* area
* current status: free, occupied, booked, reserved, maintenance
* current occupant / tenant
* rent/month
* contract end date
* issued keys
* internet and meter info
* Ausstattung
* next booking
* open documents

That means the geometry layer must link each room mesh/object to a stable room ID in the backend.

## Real-world constraints you should plan for

### 1. Source of truth for geometry

You need to decide where room dimensions come from:

* architect PDF plans
* CAD files
* IFC/BIM export
* manual measurements

This matters because if geometry changes later, you need a versioning approach.

### 2. Legal/document handling

Contracts and tenant info are sensitive. You need:

* role-based access
* audit logs
* access restriction by user group
* retention policy
* backups

### 3. Time-based truth

A room can be:

* physically the same room
* leased until June
* bookable only from July
* under maintenance in August

So avoid a single `status` field as the truth. Most room status should be **derived from dates and events**.

### 4. Keys are not just text

You will regret storing “2 keys handed out” as plain text. Track:

* key ID
* key type
* key group
* assignment date
* return date
* assigned person
* signature / note

### 5. Internet data may need more structure

“Has internet” sounds simple, but operationally you may want:

* provider
* medium: LAN/Wi-Fi/fiber
* switch/patch panel/port
* SSID/VLAN/network segment
* active/inactive
* notes

## My recommendation

If this were my system design, I would choose:

* **PostgreSQL**
* **FastAPI or Flask**
* **React**
* **2D SVG floor plan first**
* **IFC-based viewer later**
* **document upload + metadata**
* **RBAC from day one**
* **history tables for leases, keys, and bookings**

That gets you a robust operational platform without overcommitting to the 3D part too early.

## The shortest honest answer

Your idea is solid.
The **room-management portion is easy to moderately difficult**.
The **3D clickable building model is achievable but should be treated as a later visualization module**, unless you already have a usable building model.

