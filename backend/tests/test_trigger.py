from datetime import datetime, timedelta, timezone

import pytest

from app.main import app
from app.schemas import ContactSubmission
from app.workflow_trigger import get_workflow_starter
from llm_fakes import CLEAN_SIMPLE, ScriptedLLM
from repositories import workflow as workflow_repo
from repositories.agent_runs import list_agent_runs, save_agent_run
from repositories.policies import upsert_policy
from repositories.tickets import create_ticket, get_ticket, set_status
from scripts_loader import load_sample_policy
from workflow.runner import process_ticket

VALID = {
    "name": "Asha Verma", "email": "asha@example.com", "phone": "9876543210",
    "category": "complaint", "subject": "Laptop screen flickers",
    "message": "My laptop screen flickers since yesterday. Please help.",
}


def make_ticket(db, status="received", age_minutes=0):
    ticket = create_ticket(
        db,
        ContactSubmission(
            name="Asha Verma", email="asha@example.com", category="other",
            subject="Hello", message="Where is my order please?",
        ),
    )
    if age_minutes:
        ticket.created_at = datetime.now(timezone.utc) - timedelta(minutes=age_minutes)
    ticket.status = status
    db.commit()
    return ticket


@pytest.fixture()
def recorder():
    """Replaces the background starter with something that only records the call."""
    calls = []

    def start(ticket_id, claimed=False):
        calls.append((ticket_id, claimed))

    app.dependency_overrides[get_workflow_starter] = lambda: start
    return calls


# ---------- repository ----------

def test_claim_only_works_from_allowed_statuses(db):
    t = make_ticket(db, "awaiting_approval")
    assert workflow_repo.claim_for_processing(db, t.id, ("received",)) is False
    assert get_ticket(db, t.id).status == "awaiting_approval"
    t2 = make_ticket(db, "received")
    assert workflow_repo.claim_for_processing(db, t2.id, ("received",)) is True
    assert workflow_repo.claim_for_processing(db, t2.id, ("received",)) is False  # second worker loses


def test_stuck_query_rules(db):
    old_stuck = make_ticket(db, "processing", age_minutes=30)
    old_received = make_ticket(db, "received", age_minutes=30)
    fresh = make_ticket(db, "received", age_minutes=1)
    done = make_ticket(db, "awaiting_approval", age_minutes=30)
    active = make_ticket(db, "processing", age_minutes=30)
    save_agent_run(db, active.id, "understanding", 1, None, 1, 100, "ok")  # recent activity
    ids = workflow_repo.list_stuck_ticket_ids(db, older_than_minutes=10)
    assert old_stuck.id in ids and old_received.id in ids
    assert fresh.id not in ids and done.id not in ids and active.id not in ids


def test_save_result_rejects_unknown_fields(db):
    t = make_ticket(db)
    with pytest.raises(ValueError):
        workflow_repo.save_workflow_result(db, t.id, "awaiting_approval", {"final_reply": "x"})


# ---------- POST /api/contact ----------

def test_contact_queues_the_workflow(client, db, recorder):
    r = client.post("/api/contact", json=VALID)
    assert r.status_code == 201
    ticket_id = db.execute(__import__("sqlalchemy").text("select max(id) from tickets")).scalar()
    assert recorder == [(ticket_id, False)]


def test_honeypot_submission_queues_nothing(client, recorder):
    assert client.post("/api/contact", json={**VALID, "website": "http://bot.example"}).status_code == 201
    assert recorder == []


def test_form_submission_becomes_awaiting_approval(client, db, monkeypatch):
    """The 4.9 test in miniature: contact form -> background workflow -> awaiting_approval."""
    ScriptedLLM(monkeypatch, drafts=[CLEAN_SIMPLE])
    upsert_policy(db, load_sample_policy())
    app.dependency_overrides[get_workflow_starter] = lambda: (
        lambda ticket_id, claimed=False: process_ticket(db, ticket_id, claimed=claimed)
    )
    r = client.post("/api/contact", json={**VALID, "subject": "Delivery", "message": "How long is delivery?"})
    assert r.status_code == 201
    ticket_id = db.execute(__import__("sqlalchemy").text("select max(id) from tickets")).scalar()
    ticket = get_ticket(db, ticket_id)
    assert ticket.status == "awaiting_approval"
    assert ticket.draft_reply.startswith("Dear Asha Verma")


# ---------- POST /api/tickets/{id}/reprocess ----------

def test_reprocess_failed_ticket(client, db, recorder):
    t = make_ticket(db, "workflow_failed")
    r = client.post(f"/api/tickets/{t.id}/reprocess")
    assert r.status_code == 202 and r.json() == {"ticket_id": t.id, "status": "processing"}
    assert get_ticket(db, t.id).status == "processing"
    assert recorder == [(t.id, True)]
    assert list_agent_runs(db, t.id)[-1].status == "requeued"
    assert client.post(f"/api/tickets/{t.id}/reprocess").status_code == 409  # already processing


def test_reprocess_manual_reply_ticket(client, db, recorder):
    t = make_ticket(db, "needs_manual_reply")
    assert client.post(f"/api/tickets/{t.id}/reprocess").status_code == 202


@pytest.mark.parametrize("status", ["awaiting_approval", "sent", "approved_sending", "send_failed", "received"])
def test_reprocess_refused_for_other_statuses(client, db, recorder, status):
    t = make_ticket(db, status)
    assert client.post(f"/api/tickets/{t.id}/reprocess").status_code == 409
    assert get_ticket(db, t.id).status == status and recorder == []


def test_reprocess_unknown_ticket_and_auth(client, db, recorder):
    assert client.post("/api/tickets/999999/reprocess").status_code == 404
    t = make_ticket(db, "workflow_failed")
    assert client.post(f"/api/tickets/{t.id}/reprocess", headers={"X-API-Key": "wrong"}).status_code == 401


# ---------- POST /api/internal/reprocess-stuck ----------

def test_reprocess_stuck_requeues_only_stuck_tickets(client, db, recorder):
    stuck = make_ticket(db, "processing", age_minutes=30)
    fresh = make_ticket(db, "received", age_minutes=1)
    done = make_ticket(db, "awaiting_approval", age_minutes=30)
    r = client.post("/api/internal/reprocess-stuck")
    assert r.status_code == 200
    assert r.json() == {"requeued": [stuck.id], "count": 1}
    assert recorder == [(stuck.id, True)]
    assert get_ticket(db, fresh.id).status == "received"
    assert get_ticket(db, done.id).status == "awaiting_approval"
    # The marker row counts as activity, so a second scan must not queue the same ticket again.
    assert client.post("/api/internal/reprocess-stuck").json()["count"] == 0
    marker = list_agent_runs(db, stuck.id)[-1]
    assert (marker.agent_name, marker.status) == ("workflow", "requeued")


def test_reprocess_stuck_completes_a_ticket_that_died_mid_run(client, db, monkeypatch):
    """Server killed mid-run: the ticket sits in 'processing'. The recovery endpoint finishes it."""
    ScriptedLLM(monkeypatch, drafts=[CLEAN_SIMPLE])
    upsert_policy(db, load_sample_policy())
    t = make_ticket(db, "processing", age_minutes=30)
    app.dependency_overrides[get_workflow_starter] = lambda: (
        lambda ticket_id, claimed=False: process_ticket(db, ticket_id, claimed=claimed)
    )
    assert client.post("/api/internal/reprocess-stuck").json()["requeued"] == [t.id]
    assert get_ticket(db, t.id).status == "awaiting_approval"


def test_internal_endpoint_needs_the_key(client):
    assert client.post("/api/internal/reprocess-stuck", headers={"X-API-Key": "wrong"}).status_code == 401
