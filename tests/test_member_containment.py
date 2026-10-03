"""Role.MEMBER must not reach the admin surface.

Every API GET in this app authenticates with a bare `get_current_user`, and
every admin HTML view only checks that someone is signed in. That is safe while
all roles are staff, and stops being safe the moment MEMBER exists. Containment
is therefore default-deny (MemberScopeMiddleware) rather than a per-route
audit, and this module is what proves it -- including for routes that do not
exist yet.
"""

from __future__ import annotations

import pytest
from starlette.routing import Route

from app import create_app
from app.core.member_scope import MEMBER_ALLOWED_EXACT, MEMBER_ALLOWED_PREFIXES, member_may_access

#: Paths that are allowlisted but need a member surface that P1 does not ship
#: yet, or that mutate. The sweep asserts denial elsewhere; these are simply
#: out of its scope.
_SWEEP_SKIP = {
    "/api/v1/set-language",  # POST, unauthenticated by design
    "/api/v1/preferences",   # PATCH only
    "/api/v1/auth/me",       # allowlisted, asserted explicitly below
}


def _get_paths() -> list[str]:
    """Every GET path in the app, with path params filled in."""
    app = create_app()
    paths = []
    for route in app.routes:
        if not isinstance(route, Route) or "GET" not in (route.methods or set()):
            continue
        path = route.path
        if "{" in path:
            # Substitute a plausible id for every parameter.
            import re

            path = re.sub(r"\{[^}]+\}", "1", path)
        paths.append(path)
    return sorted(set(paths))


def test_allowlist_has_no_catch_all_prefix() -> None:
    """A "/" prefix would silently allow the entire application."""
    for prefix in MEMBER_ALLOWED_PREFIXES:
        assert prefix != "/", "a bare '/' prefix disables member containment entirely"
        assert len(prefix) > 1, f"suspiciously broad member prefix: {prefix!r}"
    assert "/" in MEMBER_ALLOWED_EXACT, "'/' must stay an exact match, never a prefix"


def test_prefixes_cannot_swallow_sibling_paths() -> None:
    """"/book" as a prefix would allowlist "/bookings", the staff page.

    Every prefix must end in "/" so it can only match a path *below* it.
    """
    for prefix in MEMBER_ALLOWED_PREFIXES:
        assert prefix.endswith("/"), f"member prefix {prefix!r} must end in '/'"
    assert not member_may_access("/bookings")
    assert not member_may_access("/bookings/1")
    assert member_may_access("/book")
    assert member_may_access("/book/new")


def test_member_denied_every_non_allowlisted_get(client, dev_login) -> None:
    """The sweep: default-deny across every GET route the app exposes.

    This is what covers routes added long after this test was written -- their
    author has to opt into the allowlist explicitly.
    """
    dev_login(role="member", email="member@example.com", display_name="Member User")

    leaked = []
    for path in _get_paths():
        if path in _SWEEP_SKIP or member_may_access(path):
            continue
        response = client.get(path, follow_redirects=False)
        if response.status_code == 200:
            leaked.append(path)

    assert not leaked, f"member reached non-allowlisted paths: {leaked}"


@pytest.mark.parametrize(
    "path",
    [
        "/dashboard",
        "/rooms",
        "/parties",
        "/leases",
        "/bookings",
        "/keys",
        "/documents",
        "/notifications",
        "/admin/users",
        "/admin/audit-logs",
        "/integrations",
    ],
)
def test_member_redirected_from_admin_pages(client, dev_login, path) -> None:
    dev_login(role="member", email="member@example.com", display_name="Member User")
    response = client.get(path, follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/portal"


@pytest.mark.parametrize(
    "path",
    [
        "/api/v1/bookings",
        "/api/v1/parties",
        "/api/v1/rooms",
        "/api/v1/buildings",
        "/api/v1/keys",
        "/api/v1/notifications",
        "/api/v1/admin/users",
    ],
)
def test_member_forbidden_from_admin_api(client, dev_login, path) -> None:
    dev_login(role="member", email="member@example.com", display_name="Member User")
    response = client.get(path, follow_redirects=False)
    assert response.status_code == 403, f"{path} returned {response.status_code}"


def test_member_reaches_portal_and_own_identity(client, dev_login) -> None:
    dev_login(role="member", email="member@example.com", display_name="Member User")

    portal = client.get("/portal")
    assert portal.status_code == 200
    # The portal must not render the admin navigation.
    for admin_link in ('href="/parties"', 'href="/leases"', 'href="/keys"', 'href="/admin/users"'):
        assert admin_link not in portal.text, f"portal leaks admin navigation: {admin_link}"

    me = client.get("/api/v1/auth/me")
    assert me.status_code == 200
    assert me.json()["role"] == "member"


def test_root_sends_member_to_portal(client, dev_login) -> None:
    dev_login(role="member", email="member@example.com", display_name="Member User")
    response = client.get("/", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/portal"


def test_root_still_sends_staff_to_dashboard(client, dev_login) -> None:
    dev_login(role="editor", email="editor@example.com", display_name="Editor User")
    response = client.get("/", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/dashboard"


def test_staff_unaffected_by_containment(client, dev_login) -> None:
    """The middleware must be a no-op for every non-member role."""
    dev_login(role="viewer", email="viewer@example.com", display_name="Viewer User")
    assert client.get("/dashboard").status_code == 200
    assert client.get("/api/v1/bookings").status_code == 200


def test_member_writes_denied(client, dev_login) -> None:
    """require_role tuples exclude MEMBER, so writes fail even if a path leaks."""
    csrf = dev_login(role="member", email="member@example.com", display_name="Member User")
    response = client.post(
        "/api/v1/bookings",
        json={"room_id": 1, "party_id": 1, "title": "x", "start_at": "2030-01-01T10:00:00Z",
              "end_at": "2030-01-01T11:00:00Z"},
        headers={"x-csrf-token": csrf},
    )
    assert response.status_code == 403
