from __future__ import annotations


def test_csrf_required_for_admin_user_creation(client, dev_login):
    csrf = dev_login(role="super_admin", email="root@example.com")

    no_csrf = client.post(
        "/api/v1/admin/users",
        json={"email": "new1@example.com", "display_name": "New User", "role": "viewer", "is_active": True},
    )
    assert no_csrf.status_code == 400

    with_csrf = client.post(
        "/api/v1/admin/users",
        headers={"x-csrf-token": csrf},
        json={"email": "new2@example.com", "display_name": "New User", "role": "viewer", "is_active": True},
    )
    assert with_csrf.status_code == 201


def test_role_enforced_for_admin_user_creation(client, dev_login):
    csrf = dev_login(role="viewer", email="viewer@example.com")

    response = client.post(
        "/api/v1/admin/users",
        headers={"x-csrf-token": csrf},
        json={"email": "blocked@example.com", "display_name": "Blocked", "role": "viewer", "is_active": True},
    )
    assert response.status_code == 403
