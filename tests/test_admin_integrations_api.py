from __future__ import annotations


def test_nextcloud_settings_roundtrip_and_sync_trigger(client, dev_login, monkeypatch):
    csrf = dev_login(role="admin", email="integrations-admin@example.com")

    patch_res = client.patch(
        "/api/v1/admin/integrations/nextcloud",
        headers={"x-csrf-token": csrf},
        json={
            "enabled": True,
            "url": "https://cloud.example.org",
            "admin_user": "nc-admin",
            "app_password": "app-secret",
            "ocs_version": "v2",
            "timeout_s": 45,
            "page_size": 120,
        },
    )
    assert patch_res.status_code == 200
    payload = patch_res.json()
    assert payload["enabled"] is True
    assert payload["url"] == "https://cloud.example.org"
    assert payload["admin_user"] == "nc-admin"
    assert payload["has_app_password"] is True
    assert payload["timeout_s"] == 45
    assert payload["page_size"] == 120

    get_res = client.get("/api/v1/admin/integrations/nextcloud")
    assert get_res.status_code == 200
    assert get_res.json()["has_app_password"] is True

    monkeypatch.setattr(
        "app.api.routes_admin_integrations.sync_nextcloud_person_parties",
        lambda _db, force=False: {
            "synced": 3,
            "created": 1,
            "updated": 1,
            "deactivated": 1,
            "disabled_or_missing": 0,
        },
    )
    sync_res = client.post("/api/v1/admin/integrations/nextcloud/sync-now", headers={"x-csrf-token": csrf}, json={})
    assert sync_res.status_code == 200
    assert sync_res.json()["ok"] is True
    assert sync_res.json()["stats"]["synced"] == 3
