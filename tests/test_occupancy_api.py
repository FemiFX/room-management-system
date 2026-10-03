from __future__ import annotations

from app.models.enums import PartyType
from app.models.party import Party


def test_party_delete_endpoint(client, dev_login, db_session):
    csrf = dev_login(role="admin", email="occupancy-admin@example.com")
    party = Party(party_type=PartyType.ORGANIZATION, name="Delete Me", is_active=True)
    db_session.add(party)
    db_session.commit()

    resp = client.delete(f"/api/v1/parties/{party.id}", headers={"x-csrf-token": csrf})
    assert resp.status_code == 204

    list_resp = client.get("/api/v1/parties")
    assert list_resp.status_code == 200
    assert all(p["id"] != party.id for p in list_resp.json())

