from repositories import tickets as ticket_repo

VALID = {
    "name": "Asha Verma",
    "email": "asha@example.com",
    "phone": "9876543210",
    "category": "complaint",
    "subject": "Laptop screen flickers",
    "message": "My laptop screen flickers since yesterday. Please help.",
}


def _post(client, **changes):
    return client.post("/api/contact", json={**VALID, **changes})


def test_health(client):
    assert client.get("/api/health").json() == {"status": "ok"}


def test_contact_creates_ticket(client, db):
    before = ticket_repo.list_tickets(db)[1]
    r = _post(client)
    assert r.status_code == 201
    assert r.json()["ok"] is True
    items, total = ticket_repo.list_tickets(db)
    assert total == before + 1
    assert items[0].status == "received"
    assert items[0].ip_hash and len(items[0].ip_hash) == 64


def test_contact_bad_email_returns_422(client):
    assert _post(client, email="not-an-email").status_code == 422


def test_contact_oversized_message_returns_422(client):
    assert _post(client, message="x" * 2001).status_code == 422


def test_list_tickets_returns_page(client):
    _post(client)
    r = client.get("/api/tickets")
    assert r.status_code == 200
    body = r.json()
    assert body["total"] >= 1
    assert {"id", "customer_name", "subject", "status"} <= set(body["items"][0])
    assert body["limit"] == 50


def test_list_tickets_filter_and_bad_status(client):
    _post(client)
    assert client.get("/api/tickets", params={"status": "sent"}).json()["total"] == 0
    assert client.get("/api/tickets", params={"status": "nonsense"}).status_code == 422


def test_get_ticket_and_404(client):
    _post(client, subject="Find me please")
    ticket_id = client.get("/api/tickets", params={"q": "Find me"}).json()["items"][0]["id"]
    r = client.get(f"/api/tickets/{ticket_id}")
    assert r.status_code == 200
    assert r.json()["customer_email"] == "asha@example.com"
    assert client.get("/api/tickets/99999999").status_code == 404


def test_patch_draft_saves_text(client):
    _post(client, subject="Draft edit test")
    ticket_id = client.get("/api/tickets", params={"q": "Draft edit"}).json()["items"][0]["id"]
    r = client.patch(f"/api/tickets/{ticket_id}/draft", json={"final_reply": "Hello, we will help."})
    assert r.status_code == 200
    assert r.json()["final_reply"] == "Hello, we will help."
    assert client.patch(f"/api/tickets/{ticket_id}/draft", json={"final_reply": "  "}).status_code == 422
    assert client.patch("/api/tickets/99999999/draft", json={"final_reply": "Hi"}).status_code == 404


def test_patch_draft_blocked_after_sent(client, db):
    _post(client, subject="Sent lock test")
    ticket_id = client.get("/api/tickets", params={"q": "Sent lock"}).json()["items"][0]["id"]
    ticket_repo.set_status(db, ticket_id, "sent")
    r = client.patch(f"/api/tickets/{ticket_id}/draft", json={"final_reply": "Late edit"})
    assert r.status_code == 409


def test_approve_is_a_stub(client):
    assert client.post("/api/tickets/1/approve").status_code == 501
