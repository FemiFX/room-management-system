Yes — this is exactly the right moment to design the navigation deliberately.

A room-management system like this will become messy very quickly if the sidebar is just:

* Buildings
* Floors
* Rooms
* Leases
* Bookings
* Keys
* Equipment
* Documents
* Parties

That is a **database-shaped navigation**, not an **operator-shaped navigation**.

Users do not think in tables. They think in workflows:

* “Which rooms are free?”
* “Which contracts are about to expire?”
* “Who has keys for room 2.14?”
* “What is booked next week?”
* “Which room has internet but no tenant?”
* “I need the floor plan for the first floor.”
* “I need to onboard a new tenant.”
* “I need to hand over a room and issue keys.”

So the sidebar should cluster around **jobs to be done**, while still allowing access to the core records.

The attached inspiration is useful because it already does three things well:

1. it uses **section headers** to reduce cognitive load
2. it distinguishes **high-frequency actions** from lower-level metadata
3. it avoids showing every object type as top-level first-order navigation

That is the right direction for your app too.

---

# 1. Design principle for this project

The sidebar should be built around four layers of usage:

## A. Operational overview

Where staff go to see what needs action now.

## B. Day-to-day workflows

Where staff perform core processes like assigning rooms, managing bookings, issuing keys, and uploading contracts.

## C. Spatial navigation

Where staff navigate the building itself: building → floor → room.

## D. Administrative/reference data

Where lower-frequency configuration lives: equipment types, room types, internet channels, etc.

That means the sidebar should not start with “Rooms” as the first and dominant thing. It should start with **overview and active work**.

---

# 2. The mental model behind the app

You are not really building “a room table with related records.”

You are building a **facilities operations workspace**.

The sidebar therefore should reflect these operator questions:

* What needs attention right now?
* What space do we have, and where?
* Who is occupying what?
* What is reserved when?
* What assets and infrastructure belong to which room?
* What contracts, handovers, and documents exist?
* What needs to be configured centrally?

If the nav answers those questions in that order, the product will feel coherent.

---

# 3. Recommended top-level sidebar clustering

I would structure it like this:

## OVERVIEW

* Dashboard
* Action Center

## SPACES

* Building Map
* Floors
* Rooms
* Availability

## OCCUPANCY

* Tenants / Parties
* Leases
* Check-ins / Handovers
* Expiries

## BOOKINGS

* Calendar
* Upcoming Bookings
* Booking Requests
* Bookable Rooms

## ACCESS & INFRASTRUCTURE

* Keys
* Internet & Utilities
* Equipment / Ausstattung

## DOCUMENTS

* Contracts
* Room Documents
* Handover Records

## REPORTING

* Occupancy Report
* Revenue / Rent Overview
* Room Usage

## ADMINISTRATION

* Reference Data
* Users & Roles
* Settings

That is the broad shape I would recommend.

But to make it production-useful, each item should exist for a reason.

---

# 4. Detailed process-based sidebar model

Below is the version I would actually design around.

---

## 4.1 OVERVIEW

This is where the user lands.

### 1. Dashboard

Purpose:
The operational summary page.

Shows:

* rooms occupied
* rooms free
* leases expiring soon
* upcoming bookings
* missing documents
* outstanding key returns
* rooms with incomplete data

This should be the equivalent of the “Editorial overview” in your inspiration: one page that answers, “What requires attention?”

### 2. Action Center

Purpose:
A task inbox rather than a pure analytics dashboard.

Examples:

* 3 leases expire within 30 days
* 2 rooms missing floor-plan mapping
* 1 active tenant missing signed contract upload
* 4 unreturned keys
* 2 bookings pending approval
* 5 rooms missing internet metadata

Why it should exist:
Because dashboard cards are often passive. An Action Center is process-driving.

This is where the operator goes to work through exceptions.

---

## 4.2 SPACES

This is the physical/spatial cluster.

### 3. Building Map

Purpose:
The spatial entry point into the system.

Sub-navigation could be:

* Ground Floor
* First Floor
* Second Floor

This is where your SVG-based floor plans live.

Why it belongs high in nav:
Because this app is fundamentally spatial. Users will often start from “where is the room?” rather than “which table record?”

### 4. Floors

Purpose:
A list/detail view of floors.

Useful for:

* uploading floor plans
* floor-level notes
* floor-level room counts
* navigating large buildings

This is more administrative than Building Map, but still spatial.

### 5. Rooms

Purpose:
A searchable/tabular list of all rooms.

Filters:

* free / occupied / booked
* leasable / bookable / internal
* floor
* room type
* has internet
* missing meter number
* incomplete setup

This is the master list for direct lookup and bulk management.

### 6. Availability

Purpose:
A dedicated view answering:
“What is free now / next week / next month?”

This should not be buried under bookings.

Why separate it from Rooms:
Because “room master data” and “availability planning” are different operator tasks.

For example:

* Rooms = manage room records
* Availability = plan space usage

---

## 4.3 OCCUPANCY

This cluster is about long-term usage and commercial assignment.

### 7. Tenants / Parties

Purpose:
Manage people, teams, organizations, or short-term room users.

Why not call it only “Tenants”:
Because some occupants may be internal departments, partner organizations, or event organizers.

### 8. Leases

Purpose:
The contract/occupancy list.

Filters:

* active
* draft
* expired
* expiring in 30/60/90 days
* by tenant
* by room
* by floor

This is a major operational area and should be top-level within this cluster.

### 9. Handovers

Purpose:
Manage room onboarding/offboarding events.

Includes:

* room handover
* key issue
* equipment checklist
* condition notes
* meter reading at handover
* document confirmation

Why this should be separate:
Because handover is a real process, not just a data field inside a lease.

This is one of the key places where a process-based nav becomes superior to a schema-based one.

### 10. Expiries

Purpose:
Focused operational view for:

* lease end dates
* notice periods
* pending renewals
* upcoming room release

Why not just a filter on leases:
Because this is a recurring business process and deserves its own work surface.

---

## 4.4 BOOKINGS

This cluster is for short-term room usage.

### 11. Calendar

Purpose:
Main booking interface.

Views:

* day
* week
* month
* by room
* by floor

This is where staff answer:
“When is this room booked?”

### 12. Upcoming Bookings

Purpose:
Operational list view of all imminent bookings.

Useful for:

* next 7 days
* next 30 days
* upcoming today
* room prep view

Why separate it from Calendar:
A calendar is good for visual planning; a list is better for task execution.

### 13. Booking Requests

Purpose:
If you later add approval workflows, this becomes:

* pending
* approved
* rejected
* cancelled

Even if you do not need it on day one, reserve conceptual space for it.

### 14. Bookable Rooms

Purpose:
A filtered room subset specifically for short-term resource planning.

Why include this:
Because bookable rooms often need different management than leasable rooms:

* booking rules
* opening hours
* default equipment
* cleaning buffers
* capacity

---

## 4.5 ACCESS & INFRASTRUCTURE

This cluster is important because rooms are not just commercial entities; they are operational assets.

### 15. Keys

Purpose:
Manage:

* keys
* key assignments
* returns
* missing keys
* key history

Could include subviews:

* All Keys
* Active Assignments
* Returns Due
* Lost / Deactivated

Why it deserves its own area:
Because access control is operationally critical and can become a workflow on its own.

### 16. Internet & Utilities

Purpose:
Consolidate room infrastructure.

Includes:

* internet availability
* connection channel
* provider
* switch/port/VLAN notes
* Stromzähler number
* maybe other utility identifiers later

Why cluster internet and meter here:
Because both are room infrastructure, not occupancy or booking.

You could also rename this to:

* **Infrastructure**
* **Utilities & Connectivity**
* **Technical Setup**

I would probably use **Infrastructure** in UI, and internally split models.

### 17. Equipment / Ausstattung

Purpose:
Track room contents and fixed assets.

Examples:

* desks
* projector
* whiteboard
* sink
* storage cabinets
* accessibility features
* chairs count

Why separate from room detail:
Because users may want to search for rooms by Ausstattung:

* rooms with projector
* rooms with 20 chairs
* rooms with sink
* rooms with LAN

That becomes a real workflow.

---

## 4.6 DOCUMENTS

This cluster prevents document handling from being scattered across room, lease, and handover pages.

### 18. Contracts

Purpose:
A filtered document view focused on lease/legal files.

### 19. Room Documents

Purpose:
Non-contract room files:

* floor extracts
* inspection photos
* condition reports
* compliance docs
* meter photos

### 20. Handover Records

Purpose:
Signed protocols, key issue confirmations, move-in/out documents.

Why a dedicated document cluster matters:
Operators often remember a document before they remember the exact data record it belongs to.

---

## 4.7 REPORTING

This is not just “nice to have.” It becomes essential once rooms are actually in use.

### 21. Occupancy Report

Shows:

* total rooms
* occupied rooms
* free rooms
* vacancy by floor
* vacancy by room type

### 22. Revenue / Rent Overview

Shows:

* monthly rent totals
* rooms with no active lease
* lease revenue by floor
* expiring rent streams

### 23. Room Usage

Shows:

* most booked rooms
* underused rooms
* booking density by period
* utilization trends

These do not need to be perfect initially, but the nav should reserve the conceptual space for reporting.

---

## 4.8 ADMINISTRATION

Low-frequency configuration belongs here, not in daily nav.

### 24. Reference Data

This is where your underlying master lists live:

* room types
* usage types
* equipment types
* document types
* internet connection types
* booking statuses
* lease statuses

This is the right place for model-ish configuration because it is not a daily task.

### 25. Users & Roles

Permissions and operator accounts.

### 26. Settings

Building-wide settings:

* organization details
* reminder thresholds
* booking rules
* file upload settings
* default statuses
* floor plan settings

---

# 5. What should *not* be top-level nav

To avoid the “DB dump” feeling, I would avoid putting these as first-order top-level items unless usage proves they deserve it:

* Buildings
* Equipment Types
* Internet Connections
* Documents
* Floors
* Lease Statuses
* Booking Statuses
* RoomEquipment
* KeyAssignments

These are valid models, but not primary user destinations.

They should either be:

* nested under a workflow cluster
* embedded inside detail pages
* placed under Reference Data

---

# 6. Recommended sidebar layout in the style of your inspiration

Using your screenshot as inspiration, I would structure the sidebar like this:

---

### OVERVIEW

* Dashboard
* Action Center

### SPACES

* Building Map
* Rooms
* Availability

### OCCUPANCY

* Tenants / Parties
* Leases
* Handovers
* Expiries

### BOOKINGS

* Calendar
* Upcoming Bookings
* Bookable Rooms

### ACCESS & INFRASTRUCTURE

* Keys
* Infrastructure
* Ausstattung

### DOCUMENTS

* Contracts
* Room Documents
* Handover Records

### REPORTING

* Occupancy
* Revenue
* Usage

### ADMINISTRATION

* Reference Data
* Users & Roles
* Settings

---

This is likely the cleanest first version.

---

# 7. Expand/collapse behavior

The inspiration uses expandable items. That is appropriate here too.

I would not make every section collapsible in the same way, though.

## Keep always visible

* Dashboard
* Action Center
* Building Map
* Rooms
* Calendar

These are high-frequency anchors.

## Expandable clusters

* Occupancy
* Access & Infrastructure
* Documents
* Reporting
* Administration

This keeps the sidebar compact while still discoverable.

---

# 8. Suggested priority ordering

The order matters because it implies the product’s mental model.

I would order it by operator frequency:

1. Dashboard
2. Action Center
3. Building Map
4. Rooms
5. Availability
6. Calendar
7. Leases
8. Handovers
9. Keys
10. Infrastructure
11. Ausstattung
12. Documents
13. Reporting
14. Administration

That order says:
“See what matters, navigate the space, act on occupancy and scheduling, then manage support data.”

That is the right hierarchy.

---

# 9. Page relationships and cross-navigation

The sidebar should not carry the whole burden. The page itself should expose the process flow.

For example, from a **room detail page**, the user should be able to jump directly to:

* active lease
* create booking
* issue key
* upload contract
* add equipment
* view floor plan
* mark room unavailable

From a **lease page**, the user should be able to jump to:

* tenant
* room
* handover
* contract document
* expiry workflow

From a **booking page**, the user should be able to jump to:

* room
* upcoming bookings
* calendar
* equipment setup

That way the sidebar stays clean and does not need to expose every possible operation.

---

# 10. Recommended naming decisions

A few labels will strongly affect how professional and understandable the product feels.

## Good labels

* Dashboard
* Action Center
* Building Map
* Rooms
* Availability
* Leases
* Handovers
* Calendar
* Keys
* Infrastructure
* Ausstattung
* Contracts
* Reporting
* Settings

## Labels I would avoid

* Models
* Master Data as a large visible primary nav item
* Room Management
* Lease Management
* Key Management
* Miscellaneous
* Metadata

Those feel either too technical or too generic.

If your user base is German-speaking, the labels can be localized cleanly too. For example:

* Dashboard
* Aufgaben
* Gebäudeplan
* Räume
* Verfügbarkeit
* Mietverträge
* Übergaben
* Buchungen
* Schlüssel
* Infrastruktur
* Ausstattung
* Dokumente
* Auswertungen
* Einstellungen

---

# 11. The most important structural distinction

The single most important navigation split in your app is this:

## Spatial navigation

“Where is the room?”

versus

## Process navigation

“What do I need to do?”

You need both.

That is why both of these must exist:

* **Building Map / Rooms / Availability**
* **Leases / Handovers / Calendar / Keys / Documents**

If you only build one side, the app will feel incomplete.

---

# 12. My recommended MVP sidebar

If you want the tightest, most disciplined first version, I would start with this:

### OVERVIEW

* Dashboard
* Action Center

### SPACES

* Building Map
* Rooms
* Availability

### OCCUPANCY

* Parties
* Leases
* Handovers

### BOOKINGS

* Calendar
* Upcoming Bookings

### ACCESS & INFRASTRUCTURE

* Keys
* Infrastructure
* Ausstattung

### DOCUMENTS

* Contracts
* Room Documents

### ADMINISTRATION

* Reference Data
* Settings

That is enough for a strong first system without overloading the user.

---

# 13. My recommendation for the dashboard cards

To make the sidebar meaningful, the dashboard should mirror the same process model.

Top dashboard cards should likely be:

* Free Rooms
* Occupied Rooms
* Leases Expiring Soon
* Upcoming Bookings
* Unreturned Keys
* Incomplete Room Records

Then a “Needs attention” panel like your inspiration:

* 3 leases expire in 30 days
* 2 rooms missing contracts
* 4 keys not returned
* 1 room has no meter number
* 5 bookable rooms have no next availability rule

That makes the app feel operational rather than archival.

---

# 14. Recommended information architecture rule for future features

Whenever you add a new feature, ask:

## Does this represent:

* a place?
* a process?
* an asset?
* a document?
* a configuration object?

Then place it under the right cluster.

Examples:

* maintenance tickets → Action Center or new Operations cluster
* cleaning schedules → Operations / Bookings depending on usage
* invoices → Documents or Finance if finance becomes large enough
* inspections → Documents or Operations
* utility billing → Infrastructure or Finance

This rule will keep the navigation coherent over time.

---

# 15. Final recommendation

I would design the sidebar around this logic:

* **Overview first**
* **Space second**
* **Occupancy and booking third**
* **Infrastructure and documents fourth**
* **Configuration last**

That avoids a schema dump and makes the application feel like a real workspace.
