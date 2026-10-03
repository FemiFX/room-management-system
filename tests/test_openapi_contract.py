from __future__ import annotations


EXPECTED_PATHS = {
    "/auth/login",
    "/auth/oidc",
    "/auth/callback",
    "/auth/logout",
    "/auth/dev-login",
    "/api/v1/auth/me",
    "/api/v1/set-language",
    "/api/v1/admin/users",
    "/api/v1/buildings",
    "/api/v1/rooms",
    "/api/v1/leases",
    "/api/v1/bookings",
    "/api/v1/key-assignments",
    "/api/v1/documents/upload",
    "/api/v1/notifications",
    "/api/v1/dashboard/summary",
    "/api/v1/dashboard/action-center",
    "/api/v1/preferences",
}


def test_openapi_contains_core_paths(client):
    response = client.get("/openapi.json")
    assert response.status_code == 200
    paths = set(response.json().get("paths", {}).keys())
    missing = EXPECTED_PATHS - paths
    assert not missing, f"Missing OpenAPI paths: {sorted(missing)}"
