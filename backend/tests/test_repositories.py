from app.schemas import ContactSubmission, PolicyIn
from repositories import agent_runs, policies, tickets

BIZ = 777  # isolated business id so tests never mix with other rows


def submission(**changes):
    data = {
        "name": "Asha Verma",
        "email": "asha@example.com",
        "category": "order_status",
        "subject": "Where is my order?",
        "message": "I ordered a laptop last week and it has not arrived.",
    }
    data.update(changes)
    return ContactSubmission(**data)


def new_ticket(db, **changes):
    return tickets.create_ticket(db, submission(**changes), business_id=BIZ)


def test_create_and_get_ticket(db):
    t = tickets.create_ticket(db, submission(), ip_hash="abc123", business_id=BIZ)
    assert t.id is not None
    assert t.status == "received"
    assert t.ip_hash == "abc123"
    assert t.is_spam is False
    assert t.revision_count == 0
    found = tickets.get_ticket(db, t.id, business_id=BIZ)
    assert found.id == t.id
    default = tickets.create_ticket(db, submission())
    assert default.business_id == 1


def test_get_ticket_wrong_business_returns_none(db):
    t = new_ticket(db)
    assert tickets.get_ticket(db, t.id, business_id=BIZ + 1) is None


def test_list_sorted_by_priority_nulls_last(db):
    a = new_ticket(db, subject="low")
    b = new_ticket(db, subject="high")
    new_ticket(db, subject="none")
    a.priority_score = 2.0
    b.priority_score = 9.0
    db.commit()
    items, total = tickets.list_tickets(db, business_id=BIZ)
    assert [t.subject for t in items] == ["high", "low", "none"]
    assert total == 3


def test_list_filter_by_status_and_statuses(db):
    a = new_ticket(db)
    b = new_ticket(db)
    new_ticket(db)
    tickets.set_status(db, a.id, "awaiting_approval", business_id=BIZ)
    tickets.set_status(db, b.id, "sent", business_id=BIZ)
    items, total = tickets.list_tickets(db, statuses=["sent"], business_id=BIZ)
    assert total == 1 and items[0].id == b.id
    items, total = tickets.list_tickets(
        db, statuses=["awaiting_approval", "sent"], business_id=BIZ
    )
    assert total == 2


def test_list_filter_by_category(db):
    a = new_ticket(db)
    b = new_ticket(db)
    a.category = "refund_request"
    b.category = "complaint"
    db.commit()
    items, total = tickets.list_tickets(db, category="refund_request", business_id=BIZ)
    assert total == 1 and items[0].id == a.id


def test_list_search(db):
    new_ticket(db, subject="Broken screen", message="The screen cracked on day two.")
    new_ticket(db, subject="Invoice", message="Please send my invoice copy.")
    _, total = tickets.list_tickets(db, q="screen", business_id=BIZ)
    assert total == 1
    _, total = tickets.list_tickets(db, q="SCREEN", business_id=BIZ)
    assert total == 1
    _, total = tickets.list_tickets(db, q="100%", business_id=BIZ)
    assert total == 0
    _, total = tickets.list_tickets(db, q="asha@example.com", business_id=BIZ)
    assert total == 2


def test_list_pagination(db):
    for i in range(5):
        new_ticket(db, subject=f"Ticket {i}")
    items, total = tickets.list_tickets(db, limit=2, offset=0, business_id=BIZ)
    assert len(items) == 2 and total == 5
    items, total = tickets.list_tickets(db, limit=2, offset=4, business_id=BIZ)
    assert len(items) == 1 and total == 5


def test_update_draft_saves_text(db):
    t = new_ticket(db)
    updated = tickets.update_draft(db, t.id, "Hello Asha", business_id=BIZ)
    assert updated.final_reply == "Hello Asha"
    assert updated.status == "received"


def test_update_draft_moves_manual_to_awaiting(db):
    t = new_ticket(db)
    tickets.set_status(db, t.id, "needs_manual_reply", business_id=BIZ)
    updated = tickets.update_draft(db, t.id, "My own reply", business_id=BIZ)
    assert updated.status == "awaiting_approval"
    again = tickets.update_draft(db, t.id, "Edited again", business_id=BIZ)
    assert again.status == "awaiting_approval"


def test_update_draft_unknown_ticket(db):
    assert tickets.update_draft(db, 999999999, "x", business_id=BIZ) is None


def test_set_status_with_error(db):
    t = new_ticket(db)
    failed = tickets.set_status(
        db, t.id, "send_failed", send_error="Gmail error 500", business_id=BIZ
    )
    assert failed.status == "send_failed"
    assert failed.send_error == "Gmail error 500"
    retried = tickets.set_status(db, t.id, "awaiting_approval", business_id=BIZ)
    assert retried.send_error is None


def test_set_status_sent_sets_time(db):
    t = new_ticket(db)
    sent = tickets.set_status(db, t.id, "sent", business_id=BIZ)
    assert sent.sent_at is not None
    assert tickets.set_status(db, 999999999, "sent", business_id=BIZ) is None


def test_save_and_list_agent_runs(db):
    t = new_ticket(db)
    agent_runs.save_agent_run(
        db, t.id, "understanding", 1, {"category": "complaint"}, 1, 420, "ok", business_id=BIZ
    )
    agent_runs.save_agent_run(
        db, t.id, "responder", 1, {"draft_reply": "Hi"}, 1, 800, "ok", business_id=BIZ
    )
    runs = agent_runs.list_agent_runs(db, t.id)
    assert [r.agent_name for r in runs] == ["understanding", "responder"]
    assert runs[0].output_json == {"category": "complaint"}
    assert runs[0].llm_calls == 1
    assert runs[0].duration_ms == 420


def test_get_policy_none_when_missing(db):
    assert policies.get_policy(db, business_id=999) is None


def test_upsert_policy_creates_then_updates(db):
    first = policies.upsert_policy(
        db,
        PolicyIn(business_name="TechNest", policy_text="Returns in 7 days", tone_guidelines="Polite"),
        business_id=999,
    )
    second = policies.upsert_policy(
        db,
        PolicyIn(business_name="TechNest", policy_text="Returns in 10 days", tone_guidelines="Polite"),
        business_id=999,
    )
    assert first.id == second.id
    assert policies.get_policy(db, business_id=999).policy_text == "Returns in 10 days"
