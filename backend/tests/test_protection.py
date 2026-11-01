import pytest

from app.config import settings
from app.security import limiter
from repositories import tickets as ticket_repo

VALID = {
    "name": "Asha Verma",
    "email": "asha@example.com",
    "category": "complaint",
    "subject": "Protection test",
    "message": "This is a protection layer test message.",
}


def test_owner_endpoint_without_key_returns_401(client):
    client.headers.pop("X-API-Key")
    assert client.get("/api/tickets").status_code == 401
    assert client.get("/api/tickets/1").status_code == 401
    assert client.post("/api/tickets/1/approve").status_code == 401


def test_owner_endpoint_with_wrong_key_returns_401(client):
    r = client.get("/api/tickets", headers={"X-API-Key": "wrong"})
    assert r.status_code == 401
    assert r.json() == {"detail": "Invalid or missing API key"}


def test_owner_endpoint_with_empty_server_key_is_locked(client):
    settings.internal_api_key = ""
    assert client.get("/api/tickets", headers={"X-API-Key": ""}).status_code == 401


def test_public_endpoints_need_no_key(client):
    client.headers.pop("X-API-Key")
    assert client.get("/api/health").status_code == 200
    assert client.post("/api/contact", json=VALID).status_code == 201


def test_honeypot_is_accepted_but_not_stored(client, db):
    before = ticket_repo.list_tickets(db)[1]
    r = client.post("/api/contact", json={**VALID, "website": "http://spam.example"})
    assert r.status_code == 201
    assert r.json()["ok"] is True
    assert ticket_repo.list_tickets(db)[1] == before


def test_sixth_request_in_a_minute_returns_429(client):
    limiter.enabled = True
    limiter.reset()
    codes = [client.post("/api/contact", json=VALID).status_code for _ in range(6)]
    assert codes == [201, 201, 201, 201, 201, 429]


def test_429_body_is_json(client):
    limiter.enabled = True
    limiter.reset()
    for _ in range(5):
        client.post("/api/contact", json=VALID)
    r = client.post("/api/contact", json=VALID)
    assert r.status_code == 429
    assert "detail" in r.json()
    assert r.headers["retry-after"] == "60"


def test_foreign_origin_gets_no_cors_header(client):
    r = client.options(
        "/api/contact",
        headers={
            "Origin": "https://evil.example",
            "Access-Control-Request-Method": "POST",
        },
    )
    assert "access-control-allow-origin" not in r.headers


def test_allowed_origin_gets_cors_header(client):
    if not settings.origins_list:
        pytest.skip("ALLOWED_ORIGINS is empty in backend/.env")
    origin = settings.origins_list[0]
    r = client.options(
        "/api/contact",
        headers={"Origin": origin, "Access-Control-Request-Method": "POST"},
    )
    assert r.headers.get("access-control-allow-origin") == origin
