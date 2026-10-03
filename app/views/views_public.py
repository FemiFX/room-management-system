"""The public booking form.

The only unauthenticated surface in RMS. Two deliberate departures from the
conventions elsewhere in `app/views`:

1. These pages render without `base_admin_context` and extend `base.html`
   directly, like `auth/login.html`. The admin layout would leak staff
   navigation to the public.
2. Submission is a real form POST that re-renders with errors, not a fetch()
   to /api/v1. The rest of the app is GET-only views plus JS, but a public
   form has to work without JavaScript. `verify_csrf` already reads
   `csrf_token` from a urlencoded body, so this needs no change there.
"""

from __future__ import annotations

import logging
from datetime import datetime, time, timedelta

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.api.deps import verify_csrf
from app.core.i18n import gettext, N_
from app.core.templating import templates
from app.core.time_utils import app_now, to_app_tz
from app.db.session import get_db
from app.models.booking import Booking
from app.models.booking_request import BookingRequest
from app.models.booking_service import BookingService
from app.models.enums import BookingSource, BookingStatus
from app.models.equipment import RoomEquipment
from app.models.room import Room
from app.models.room_service import RoomService
from app.services.booking_documents import (
    ALLOWED_TYPES as ALLOWED_DOCUMENT_TYPES,
    MAX_BYTES as MAX_DOCUMENT_BYTES,
    DocumentRejected,
    find_certificate,
    store_certificate,
)
from app.services.booking_notifications import notify, notify_public_request_created
from app.services.calendar import build_month, resolve_month
from app.services.booking_tokens import manage_url, read_manage_token
from app.services.bookings import (
    BookingError,
    BookingInput,
    EquipmentLine,
    PublicRequesterInput,
    RoomUnavailable,
    ServiceLine,
    TimeframeInput,
    cancel_booking,
    create_booking,
    modify_booking,
    resolve_public_requester,
)
from app.services.rate_limit import RateLimited, client_ip, hit
from app.views.public_deps import hash_ip, public_context

router = APIRouter()

logger = logging.getLogger(__name__)

_HOUR = 3600


def _t(request, message: str) -> str:
    return gettext(message, request=request, user=None)


def _document_error(request, code: str) -> str:
    """Real literals, one per rejection reason.

    The messages have to be written out here rather than taken from the
    exception: a msgid assembled at runtime is never extracted, and shows up
    in English on a German page.
    """
    if code == "too_large":
        return _t(request, "That file is larger than 10 MB.")
    if code == "empty":
        return _t(request, "That file is empty.")
    return _t(request, "Please upload a PDF, JPG or PNG.")


def _public_rooms(db: Session) -> list[Room]:
    return list(
        db.scalars(
            select(Room)
            .where(Room.is_active.is_(True), Room.public_bookable.is_(True))
            .options(
                joinedload(Room.room_equipment).joinedload(RoomEquipment.equipment),
                joinedload(Room.service_links).joinedload(RoomService.service),
            )
            .order_by(Room.name.asc())
        ).unique().all()
    )


#: The six things people most often tell us, as a tick list on step 4. The
#: key is what the form posts; the text is composed into the free-text note on
#: submit, so the record still holds one answer in the requester's language.
_NOTE_FLAGS: tuple[tuple[str, str], ...] = (
    ("step_free", N_("Step-free access needed")),
    ("own_equipment", N_("We bring our own equipment")),
    ("setup_day_before", N_("Set-up or take-down the day before")),
    ("catering", N_("Catering in the room")),
    ("children", N_("Children will be there")),
    ("press", N_("Press or photos planned")),
)


def _note_flags(request) -> list[tuple[str, str]]:
    return [(key, _t(request, text)) for key, text in _NOTE_FLAGS]


def _compose_note(request, form, free_text: str) -> str:
    """Ticked boxes first, then whatever they wrote."""
    lines = [_t(request, text) for key, text in _NOTE_FLAGS if form.get(f"note_{key}")]
    written = (free_text or "").strip()
    if written:
        lines.append(written)
    return "\n".join(lines)


def _requestable(room: Room) -> list[RoomEquipment]:
    """The room's loose equipment -- what a booking can actually order.

    Permanently installed kit (``fixed``) is shown on the form as part of the
    room and has no quantity field, so a crafted POST must not create a line
    for it either.
    """
    return [link for link in room.room_equipment if not link.fixed]


def _chosen_lines(form) -> tuple[dict[int, str], set[int]]:
    """What the visitor had entered, keyed the way the room picker reads it.

    Used when a submit bounces back with errors: without it the equipment
    numbers and the ticked services would come back empty.
    """
    quantities: dict[int, str] = {}
    services: set[int] = set()
    for key, value in form.items():
        # `equipment_<room>_<equipment>` -- the picker keys the field by both.
        if key.startswith("equipment_") and str(value).strip():
            try:
                quantities[int(key.rsplit("_", 1)[1])] = str(value)
            except (IndexError, ValueError):
                continue
        elif key.startswith("service_") and value:
            try:
                services.add(int(key.rsplit("_", 1)[1]))
            except (IndexError, ValueError):
                continue
    return quantities, services


def _as_room_id(raw) -> int | None:
    return int(raw) if str(raw or "").isdigit() else None


def _active_services(db: Session) -> list[BookingService]:
    return list(
        db.scalars(
            select(BookingService)
            .where(BookingService.is_active.is_(True))
            .order_by(BookingService.sort_order.asc())
        ).all()
    )


def _room_services(room: Room) -> list[BookingService]:
    """The active services THIS room offers.

    Services used to be global, so every room showed the whole catalogue. The
    room_services link table (20260903_0017) decides it per room now, and this
    is the single place that reads it -- the form renders from it and the
    submit handler filters against it, so a crafted POST cannot request a
    service the chosen room does not offer.
    """
    return sorted(
        (link.service for link in room.service_links if link.service and link.service.is_active),
        key=lambda service: (service.sort_order, service.name),
    )


@router.get("/book", response_class=HTMLResponse)
def book_landing(request: Request, db: Session = Depends(get_db)):
    ctx = public_context(request, rooms=_public_rooms(db))
    return templates.TemplateResponse(request, "public/landing.html", ctx)


@router.get("/book/calendar", response_class=HTMLResponse)
def book_calendar(
    request: Request,
    year: int | None = None,
    month: int | None = None,
    db: Session = Depends(get_db),
):
    """Public availability, month by month.

    Only publicly bookable rooms, only confirmed bookings, and no titles -- the
    same disclosure rule as /api/v1/public/rooms/{id}/availability. The
    reference app's calendar published every booking's event title to the
    world under open CORS.
    """
    year, month = resolve_month(year, month)
    grid = build_month(
        db, year=year, month=month, rooms=_public_rooms(db), include_titles=False
    )
    ctx = public_context(request, month=grid)
    return templates.TemplateResponse(request, "public/calendar.html", ctx)


@router.get("/book/new", response_class=HTMLResponse)
def book_form(request: Request, room: str = "", db: Session = Depends(get_db)):
    """The request form.

    ``?room=`` preselects a room, which is how the cards on the landing page
    and the calendar hand over what the visitor already chose. An id that is
    not a bookable room is ignored rather than refused: a stale link should
    open the form, not an error page.
    """
    rooms = _public_rooms(db)
    wanted = _as_room_id(room)
    preselected = wanted if any(r.id == wanted for r in rooms) else None
    ctx = public_context(
        request,
        rooms=rooms,
        # Keyed by room: the form only offers what the chosen room offers.
        room_services={room.id: _room_services(room) for room in rooms},
        selected_equipment={},
        selected_services=set(),
        checked_room_id=preselected,
        note_flags=_note_flags(request),
        form={},
        errors={},
        min_date=(app_now() + timedelta(days=1)).date().isoformat(),
    )
    return templates.TemplateResponse(request, "public/form.html", ctx)


def _parse_datetime(day: str, clock: str, fallback: time) -> datetime | None:
    if not day:
        return None
    try:
        parsed_date = datetime.strptime(day, "%Y-%m-%d").date()
    except ValueError:
        return None
    parsed_time = fallback
    if clock:
        for fmt in ("%H:%M", "%H:%M:%S"):
            try:
                parsed_time = datetime.strptime(clock, fmt).time()
                break
            except ValueError:
                continue
    return to_app_tz(datetime.combine(parsed_date, parsed_time))


@router.post("/book/submit", response_class=HTMLResponse, dependencies=[Depends(verify_csrf)])
async def book_submit(
    request: Request,
    db: Session = Depends(get_db),
    first_name: str = Form(""),
    last_name: str = Form(""),
    academic_title: str = Form(""),
    organization: str = Form(""),
    email: str = Form(""),
    phone: str = Form(""),
    address: str = Form(""),
    contact_person: str = Form(""),
    event_title: str = Form(""),
    start_date: str = Form(""),
    start_time: str = Form(""),
    end_date: str = Form(""),
    end_time: str = Form(""),
    whole_day: str = Form(""),
    room_id: str = Form(""),
    participants: str = Form(""),
    billing_info: str = Form(""),
    additional_info: str = Form(""),
    liability_insurance: str = Form(""),
    #: Optional at submit time on purpose. Somebody filling this in on a phone
    #: rarely has the certificate to hand, and refusing the whole request over
    #: a missing attachment would cost us the booking, not gain us the cover.
    insurance_document: UploadFile | None = File(default=None),
    # Honeypot: a real person never fills this in, but a naive bot fills
    # everything. Cheaper and more accessible than a captcha.
    website: str = Form(""),
):
    form = await request.form()
    _rooms = _public_rooms(db)
    ctx_extra = {
        "rooms": _rooms,
        "room_services": {room.id: _room_services(room) for room in _rooms},
        "min_date": (app_now() + timedelta(days=1)).date().isoformat(),
        "note_flags": _note_flags(request),
    }

    def rerender(errors: dict[str, str], status_code: int = 400):
        quantities, services = _chosen_lines(form)
        ctx = public_context(
            request, form=dict(form), errors=errors,
            selected_equipment=quantities,
            selected_services=services,
            checked_room_id=_as_room_id(form.get("room_id")),
            **ctx_extra,
        )
        return templates.TemplateResponse(
            request, "public/form.html", ctx, status_code=status_code
        )

    if website:
        # Pretend it worked. Telling a bot it was detected only helps it.
        return RedirectResponse(url="/book/thanks", status_code=303)

    if not form.get("privacy_consent"):
        return rerender(
            {"privacy_consent": _t(request, "Please confirm the privacy policy first.")}
        )

    address_ip = client_ip(request)
    try:
        hit(f"book:ip:{address_ip}", limit=5, window_seconds=_HOUR)
        if email:
            hit(f"book:email:{email.strip().lower()}", limit=3, window_seconds=_HOUR)
    except RateLimited:
        return rerender(
            {"__all__": _t(request, "Too many requests. Please try again later.")}, status_code=429
        )

    errors: dict[str, str] = {}
    if not email.strip():
        errors["email"] = _t(request, "An email address is required.")
    if not event_title.strip():
        errors["event_title"] = _t(request, "Please give your event a title.")
    if not room_id:
        errors["room_id"] = _t(request, "Please choose a room.")

    is_whole_day = bool(whole_day)
    start_at = _parse_datetime(start_date, start_time, time(0, 0))
    end_at = _parse_datetime(end_date or start_date, end_time, time(23, 59))
    if start_at is None:
        errors["start_date"] = _t(request, "Please give a valid start date.")
    if end_at is None:
        errors["end_date"] = _t(request, "Please give a valid end date.")
    if errors:
        return rerender(errors)

    room = db.scalar(
        select(Room).where(
            Room.id == int(room_id), Room.is_active.is_(True), Room.public_bookable.is_(True)
        )
    )
    if room is None:
        return rerender({"room_id": _t(request, "That room cannot be booked online.")})

    equipment_lines, service_lines = _lines_from_form(db, room, form)

    attendee_count = None
    if participants.strip():
        try:
            attendee_count = int(participants)
        except ValueError:
            return rerender({"participants": _t(request, "Please give a number of attendees.")})

    # Three states: yes, no, and never answered. Anything else the browser
    # might send is not an answer.
    insured = {"yes": True, "no": False}.get(liability_insurance.strip().lower())

    certificate_blob = b""
    if insured and insurance_document is not None and insurance_document.filename:
        certificate_blob = await insurance_document.read()
        if len(certificate_blob) > MAX_DOCUMENT_BYTES:
            return rerender({"insurance_document": _t(request, "That file is larger than 10 MB.")})
        if (insurance_document.content_type or "").lower() not in ALLOWED_DOCUMENT_TYPES:
            return rerender({"insurance_document": _t(request, "Please upload a PDF, JPG or PNG.")})

    language = public_context(request)["current_language"]
    requester = PublicRequesterInput(
        email=email.strip().lower(),
        first_name=first_name.strip() or None,
        last_name=last_name.strip() or None,
        academic_title=academic_title.strip() or None,
        organization=organization.strip() or None,
        phone=phone.strip() or None,
        address=address.strip() or None,
    )

    try:
        hit(f"book:room:{room.id}", limit=20, window_seconds=_HOUR)
        party = resolve_public_requester(db, requester)
        booking = create_booking(
            db,
            room=room,
            party=party,
            data=BookingInput(
                room_id=room.id,
                title=event_title.strip(),
                timeframe=TimeframeInput(start_at=start_at, end_at=end_at, whole_day=is_whole_day),
                purpose="public booking request",
                attendee_count=attendee_count,
                contact_person=contact_person.strip() or None,
                billing_info=billing_info.strip() or None,
                additional_info=_compose_note(request, form, additional_info) or None,
                liability_insurance=insured,
                language=language,
                equipment=equipment_lines,
                services=service_lines,
            ),
            source=BookingSource.PUBLIC,
            # A request, not a reservation. Staff decide, and that is where the
            # conflict check bites.
            status=BookingStatus.PENDING,
            actor_user_id=None,
            requester=requester,
            submitted_ip_hash=hash_ip(address_ip),
        )
    except RateLimited:
        return rerender(
            {"__all__": _t(request, "Too many requests. Please try again later.")}, status_code=429
        )
    except RoomUnavailable as exc:
        return rerender({"__all__": str(exc)}, status_code=409)
    except BookingError as exc:
        return rerender({"__all__": str(exc)})

    db.refresh(booking)

    # After the booking is committed: a storage failure must not lose the
    # request, which is the thing that actually matters here.
    if certificate_blob:
        try:
            store_certificate(
                db,
                booking,
                filename=insurance_document.filename,
                content_type=insurance_document.content_type,
                blob=certificate_blob,
            )
        except Exception as exc:
            # Deliberately swallowed, DocumentRejected included. The booking
            # stands, the answer is recorded as "yes", and the admin card says
            # the certificate is still outstanding -- recoverable, unlike a 500
            # on a form the visitor has already filled in once.
            logger.warning("could not store certificate for booking %s: %s", booking.id, exc)

    link = manage_url(
        booking_request_id=booking.request.id, token_version=booking.request.token_version
    )
    notify_public_request_created(db, booking, manage_url=link)

    return RedirectResponse(
        url=f"/book/confirmation/{booking.request.public_ref}", status_code=303
    )


@router.get("/book/confirmation/{public_ref}", response_class=HTMLResponse)
def confirmation(public_ref: str, request: Request, db: Session = Depends(get_db)):
    booking_request = db.scalar(
        select(BookingRequest).where(BookingRequest.public_ref == public_ref)
    )
    ctx = public_context(request, public_ref=public_ref, found=booking_request is not None)
    return templates.TemplateResponse(request, "public/confirmation.html", ctx)


@router.get("/book/thanks", response_class=HTMLResponse)
def thanks(request: Request):
    """Where a honeypot submission lands, indistinguishable from success."""
    ctx = public_context(request, public_ref=None, found=False)
    return templates.TemplateResponse(request, "public/confirmation.html", ctx)


@router.get("/book/retrieve", response_class=HTMLResponse)
def retrieve_form(request: Request):
    ctx = public_context(request, sent=False, errors={})
    return templates.TemplateResponse(request, "public/retrieve.html", ctx)


@router.post("/book/retrieve", response_class=HTMLResponse, dependencies=[Depends(verify_csrf)])
def retrieve_submit(
    request: Request,
    db: Session = Depends(get_db),
    public_ref: str = Form(""),
    email: str = Form(""),
):
    """Email the manage link to the address on file.

    The response is identical whether or not the reference exists. That is the
    whole point: the reference app returned 404 for an unknown booking number
    and 200 for a known one, which is an enumeration oracle over a 900,000-wide
    space with no rate limit.
    """
    try:
        hit(f"retrieve:ip:{client_ip(request)}", limit=5, window_seconds=_HOUR)
    except RateLimited:
        ctx = public_context(
            request,
            sent=False,
            errors={"__all__": _t(request, "Too many requests. Please try again later.")},
        )
        return templates.TemplateResponse(request, "public/retrieve.html", ctx, status_code=429)

    booking_request = db.scalar(
        select(BookingRequest).where(BookingRequest.public_ref == public_ref.strip().upper())
    )
    if (
        booking_request is not None
        and booking_request.requester_email
        and booking_request.requester_email == email.strip().lower()
    ):
        booking = db.get(Booking, booking_request.booking_id)
        if booking is not None:
            notify(
                booking,
                "public_booking_manage_link",
                manage_url=manage_url(
                    booking_request_id=booking_request.id,
                    token_version=booking_request.token_version,
                ),
            )

    ctx = public_context(request, sent=True, errors={})
    return templates.TemplateResponse(request, "public/retrieve.html", ctx)


def _booking_for_token(db: Session, token: str) -> Booking | None:
    payload = read_manage_token(token)
    if payload is None:
        return None
    request_id, version = payload
    booking_request = db.get(BookingRequest, request_id)
    if booking_request is None or booking_request.token_version != version:
        return None
    return db.get(Booking, booking_request.booking_id)


def _lines_from_form(db: Session, room: Room, form) -> tuple[list[EquipmentLine], list[ServiceLine]]:
    equipment: list[EquipmentLine] = []
    # `fixed` equipment is installed in the room -- it comes with it and is not
    # something a request orders three of. The form lists it, without a field.
    for link in _requestable(room):
        raw = form.get(f"equipment_{room.id}_{link.equipment_id}")
        try:
            quantity = int(raw) if raw else 0
        except ValueError:
            quantity = 0
        if quantity > 0:
            equipment.append(EquipmentLine(link.equipment_id, quantity))
    services = [
        ServiceLine(service.id)
        for service in _room_services(room)
        if form.get(f"service_{room.id}_{service.id}")
    ]
    return equipment, services


@router.get("/book/manage", response_class=HTMLResponse)
def manage(request: Request, t: str = "", db: Session = Depends(get_db)):
    booking = _booking_for_token(db, t)
    if booking is None:
        ctx = public_context(request)
        return templates.TemplateResponse(request, "public/link_invalid.html", ctx, status_code=403)

    ctx = public_context(
        request, booking=booking, booking_request=booking.request, token=t,
        certificate=find_certificate(db, booking.id),
    )
    return templates.TemplateResponse(request, "public/manage.html", ctx)


@router.post("/book/manage/insurance", response_class=HTMLResponse, dependencies=[Depends(verify_csrf)])
async def manage_upload_insurance(
    request: Request,
    t: str = Form(""),
    insurance_document: UploadFile | None = File(default=None),
    db: Session = Depends(get_db),
):
    """The "send it on later" half of the liability question.

    Authorised by the same signed manage token as cancelling and editing -- so
    it is revocable, expires, and cannot be reached by guessing a reference.
    """
    booking = _booking_for_token(db, t)
    if booking is None:
        ctx = public_context(request)
        return templates.TemplateResponse(request, "public/link_invalid.html", ctx, status_code=403)

    def rerender(error: str | None = None, status_code: int = 200):
        ctx = public_context(
            request, booking=booking, booking_request=booking.request, token=t,
            certificate=find_certificate(db, booking.id), insurance_error=error,
        )
        return templates.TemplateResponse(request, "public/manage.html", ctx, status_code=status_code)

    # Uploading is cheap for us and expensive to abuse; the same per-IP budget
    # the rest of this surface uses applies.
    try:
        hit(f"insurance:ip:{client_ip(request)}", limit=20, window_seconds=_HOUR)
    except RateLimited:
        return rerender(_t(request, "Too many requests. Please try again later."), status_code=429)

    if insurance_document is None or not insurance_document.filename:
        return rerender(_t(request, "Please choose a file."), status_code=400)

    try:
        store_certificate(
            db,
            booking,
            filename=insurance_document.filename,
            content_type=insurance_document.content_type,
            blob=await insurance_document.read(),
        )
    except DocumentRejected as exc:
        return rerender(_document_error(request, exc.code), status_code=400)

    # Saying "yes" is implied by producing the certificate. A request that
    # answered "no" and then sent proof anyway has changed its answer.
    if booking.request is not None and booking.request.liability_insurance is not True:
        booking.request.liability_insurance = True
        db.commit()

    _notify_staff_of_change(db, booking, title="Insurance certificate received")
    return rerender()


@router.post("/book/manage/cancel", response_class=HTMLResponse, dependencies=[Depends(verify_csrf)])
def manage_cancel(request: Request, t: str = Form(""), db: Session = Depends(get_db)):
    booking = _booking_for_token(db, t)
    if booking is None:
        ctx = public_context(request)
        return templates.TemplateResponse(request, "public/link_invalid.html", ctx, status_code=403)

    if booking.status not in {BookingStatus.PENDING, BookingStatus.APPROVED}:
        ctx = public_context(request, booking=booking, booking_request=booking.request, token=t)
        return templates.TemplateResponse(request, "public/manage.html", ctx)

    cancelled = cancel_booking(db, booking=booking, cancelled_by="customer", actor_user_id=None)
    notify(cancelled, "public_booking_cancelled")
    ctx = public_context(request, cancelled=True, public_ref=cancelled.request.public_ref)
    return templates.TemplateResponse(request, "public/cancelled.html", ctx)


@router.get("/book/manage/edit", response_class=HTMLResponse)
def manage_edit_form(request: Request, t: str = "", db: Session = Depends(get_db)):
    """The customer's own edit page, reached only from the emailed link.

    The reference app served the equivalent at /modify_booking/<number> with no
    authentication at all -- an enumerable six-digit number gave read and write
    access to a stranger's name, email, address and billing details. Here the
    signed token is the only way in.
    """
    booking = _booking_for_token(db, t)
    if booking is None:
        ctx = public_context(request)
        return templates.TemplateResponse(request, "public/link_invalid.html", ctx, status_code=403)

    if booking.status not in {BookingStatus.PENDING, BookingStatus.APPROVED}:
        # A rejected or cancelled booking is not editable back into life.
        ctx = public_context(request, booking=booking, booking_request=booking.request, token=t)
        return templates.TemplateResponse(request, "public/manage.html", ctx)

    _edit_rooms = _public_rooms(db)
    ctx = public_context(
        request,
        booking=booking,
        booking_request=booking.request,
        token=t,
        rooms=_edit_rooms,
        room_services={room.id: _room_services(room) for room in _edit_rooms},
        selected_equipment={line.equipment_id: line.quantity for line in booking.equipment_requests},
        selected_services={line.service_id for line in booking.service_requests},
        checked_room_id=booking.room_id,
        errors={},
        min_date=(app_now() + timedelta(days=1)).date().isoformat(),
    )
    return templates.TemplateResponse(request, "public/manage_edit.html", ctx)


@router.post("/book/manage/edit", response_class=HTMLResponse, dependencies=[Depends(verify_csrf)])
async def manage_edit_submit(request: Request, db: Session = Depends(get_db)):
    form = await request.form()
    token = str(form.get("t") or "")
    booking = _booking_for_token(db, token)
    if booking is None:
        ctx = public_context(request)
        return templates.TemplateResponse(request, "public/link_invalid.html", ctx, status_code=403)
    if booking.status not in {BookingStatus.PENDING, BookingStatus.APPROVED}:
        ctx = public_context(request, booking=booking, booking_request=booking.request, token=token)
        return templates.TemplateResponse(request, "public/manage.html", ctx)

    try:
        hit(f"edit:ip:{client_ip(request)}", limit=20, window_seconds=_HOUR)
    except RateLimited:
        ctx = public_context(request)
        return templates.TemplateResponse(request, "public/link_invalid.html", ctx, status_code=429)

    edit_rooms = _public_rooms(db)

    def rerender(errors: dict[str, str], status_code: int = 400):
        ctx = public_context(
            request,
            booking=booking,
            booking_request=booking.request,
            token=token,
            rooms=edit_rooms,
            room_services={room.id: _room_services(room) for room in edit_rooms},
            selected_equipment=_chosen_lines(form)[0],
            selected_services=_chosen_lines(form)[1],
            checked_room_id=_as_room_id(form.get("room_id")) or booking.room_id,
            form=dict(form),
            errors=errors,
            min_date=(app_now() + timedelta(days=1)).date().isoformat(),
        )
        return templates.TemplateResponse(
            request, "public/manage_edit.html", ctx, status_code=status_code
        )

    event_title = str(form.get("event_title") or "").strip()
    room_id = str(form.get("room_id") or "")
    if not event_title:
        return rerender({"event_title": _t(request, "Please give your event a title.")})
    if not room_id:
        return rerender({"room_id": _t(request, "Please choose a room.")})

    room = db.scalar(
        select(Room).where(
            Room.id == int(room_id), Room.is_active.is_(True), Room.public_bookable.is_(True)
        )
    )
    if room is None:
        return rerender({"room_id": _t(request, "That room cannot be booked online.")})

    is_whole_day = bool(form.get("whole_day"))
    start_at = _parse_datetime(
        str(form.get("start_date") or ""), str(form.get("start_time") or ""), time(0, 0)
    )
    end_at = _parse_datetime(
        str(form.get("end_date") or form.get("start_date") or ""),
        str(form.get("end_time") or ""),
        time(23, 59),
    )
    if start_at is None:
        return rerender({"start_date": _t(request, "Please give a valid start date.")})
    if end_at is None:
        return rerender({"end_date": _t(request, "Please give a valid end date.")})

    attendee_count = None
    participants = str(form.get("participants") or "").strip()
    if participants:
        try:
            attendee_count = int(participants)
        except ValueError:
            return rerender({"participants": _t(request, "Please give a number of attendees.")})

    equipment_lines, service_lines = _lines_from_form(db, room, form)
    existing_request = booking.request

    try:
        modify_booking(
            db,
            booking=booking,
            room=room,
            data=BookingInput(
                room_id=room.id,
                title=event_title,
                timeframe=TimeframeInput(start_at=start_at, end_at=end_at, whole_day=is_whole_day),
                purpose=booking.purpose,
                attendee_count=attendee_count,
                contact_person=str(form.get("contact_person") or "").strip() or None,
                billing_info=str(form.get("billing_info") or "").strip() or None,
                additional_info=str(form.get("additional_info") or "").strip() or None,
                language=existing_request.language if existing_request else "de",
                equipment=equipment_lines,
                services=service_lines,
            ),
            actor_user_id=None,
            requester=PublicRequesterInput(
                # The email is not editable: it is the address the link was
                # sent to and the key the party was resolved by.
                email=existing_request.requester_email or "",
                first_name=str(form.get("first_name") or "").strip() or None,
                last_name=str(form.get("last_name") or "").strip() or None,
                academic_title=str(form.get("academic_title") or "").strip() or None,
                organization=str(form.get("organization") or "").strip() or None,
                phone=str(form.get("phone") or "").strip() or None,
                address=str(form.get("address") or "").strip() or None,
            ),
        )
    except RoomUnavailable as exc:
        return rerender({"__all__": str(exc)}, status_code=409)
    except BookingError as exc:
        return rerender({"__all__": str(exc)})

    db.refresh(booking)
    link = manage_url(
        booking_request_id=booking.request.id, token_version=booking.request.token_version
    )
    notify(booking, "public_booking_modified", manage_url=link)
    _notify_staff_of_change(db, booking)

    return RedirectResponse(url=f"/book/manage/updated?t={token}", status_code=303)


@router.get("/book/manage/updated", response_class=HTMLResponse)
def manage_updated(request: Request, t: str = "", db: Session = Depends(get_db)):
    booking = _booking_for_token(db, t)
    if booking is None:
        ctx = public_context(request)
        return templates.TemplateResponse(request, "public/link_invalid.html", ctx, status_code=403)
    ctx = public_context(
        request, booking=booking, booking_request=booking.request, token=t
    )
    return templates.TemplateResponse(request, "public/manage_updated.html", ctx)


def _notify_staff_of_change(db: Session, booking: Booking, title: str = "Booking request changed") -> None:
    """Staff must find out that an agreed booking changed under them."""
    from app.services.notifications import fanout_admin_notification

    try:
        fanout_admin_notification(
            db,
            title=title,
            message=f"{booking.title} — {booking.room.name if booking.room else ''}",
            link=f"/bookings/{booking.id}",
            details_json={"booking_id": booking.id},
        )
        db.commit()
    except Exception:
        db.rollback()
