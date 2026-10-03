"""Signed links for managing a public booking.

The reference app authorised nothing: `/modify_booking/<n>` took a six-digit
number in the URL and gave full read *and write* access to a stranger's name,
email, postal address and billing details -- enumerable, unrate-limited, and
inconsistent with its own cancellation flow, which at least asked for a code.

Here, the reference and the credential are separate things:

  - `public_ref` (RB-XXXXXXXX) is a *quotable reference*. It identifies a
    booking in an email or over the phone and authorises nothing.
  - the manage token is a signed, expiring, revocable credential, only ever
    delivered to the address on the booking.

Revocation needs no server-side store: the token carries the request's
`token_version`, and bumping that column invalidates every link already sent.
"""

from __future__ import annotations

from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from app.core.config import get_settings

_SALT = "public-booking-manage"

#: Long enough to cover a booking made far in advance, short enough that an
#: old mailbox is not a permanent key.
MAX_TOKEN_AGE_SECONDS = 180 * 24 * 60 * 60


def _serializer() -> URLSafeTimedSerializer:
    # Keyed on the app secret, so rotating RMS_SECRET_KEY invalidates every
    # outstanding manage link along with every session.
    return URLSafeTimedSerializer(get_settings().secret_key, salt=_SALT)


def make_manage_token(*, booking_request_id: int, token_version: int) -> str:
    return _serializer().dumps({"br": booking_request_id, "v": token_version})


def read_manage_token(token: str) -> tuple[int, int] | None:
    """Return ``(booking_request_id, token_version)``, or None if unusable.

    Tampering, expiry and malformed payloads are all the same answer to the
    caller: no access. Distinguishing them would leak whether a token was ever
    valid.
    """
    try:
        payload = _serializer().loads(token, max_age=MAX_TOKEN_AGE_SECONDS)
    except (BadSignature, SignatureExpired):
        return None
    if not isinstance(payload, dict):
        return None
    try:
        return int(payload["br"]), int(payload["v"])
    except (KeyError, TypeError, ValueError):
        return None


def manage_url(*, booking_request_id: int, token_version: int) -> str:
    base = get_settings().public_base_url.rstrip("/")
    token = make_manage_token(booking_request_id=booking_request_id, token_version=token_version)
    return f"{base}/book/manage?t={token}"
