from app.schemas import ContactSubmission
from llm_fakes import CLEAN_RISKY, CLEAN_SIMPLE, REFUND_PROMISE, FakeAPIError, ScriptedLLM, analysis
from repositories.agent_runs import list_agent_runs
from repositories.policies import upsert_policy
from repositories.tickets import create_ticket, get_ticket
from scripts_loader import load_sample_policy
from workflow import runner
from workflow.runner import REPROCESS_FROM, process_ticket

NAME, EMAIL, PHONE = "Asha Verma", "asha@example.com", "+91 98765 43210"


def make_ticket(db, message=None, subject="Shipping question", category="other"):
    upsert_policy(db, load_sample_policy())
    return create_ticket(
        db,
        ContactSubmission(
            name=NAME, email=EMAIL, phone=PHONE, category=category, subject=subject,
            message=message or f"Hi, I am {NAME}. Write to {EMAIL} or call {PHONE}. How long is delivery?",
        ),
    )


def test_happy_path_saves_everything_on_the_ticket(db, monkeypatch):
    fake = ScriptedLLM(monkeypatch, drafts=[CLEAN_SIMPLE])
    ticket = make_ticket(db)
    outcome = process_ticket(db, ticket.id)
    assert outcome.status == "awaiting_approval" and outcome.llm_calls == 2 and outcome.error is None

    t = get_ticket(db, ticket.id)
    assert t.status == "awaiting_approval"
    assert t.category == "product_inquiry" and t.intent and t.summary and t.is_spam is False
    assert t.urgency_score == 2 and t.sentiment == "neutral" and t.loss_risk == "low"
    assert t.priority_score is not None and t.risk_reasons
    assert t.draft_reply.startswith("Dear Asha Verma,")  # code filled in the real name
    assert t.compliance_status == "passed" and t.compliance_violations == []
    assert t.revision_count == 0
    assert t.final_reply is None  # only the owner writes this


def test_no_personal_details_reach_the_llm(db, monkeypatch):
    fake = ScriptedLLM(
        monkeypatch, analysis_=analysis(category="complaint", loss="high"), drafts=[CLEAN_RISKY]
    )
    ticket = make_ticket(db)
    process_ticket(db, ticket.id)
    assert fake.prompts
    for _, prompt in fake.prompts:
        assert NAME not in prompt and "Asha" not in prompt
        assert EMAIL not in prompt and "98765" not in prompt


def test_obvious_spam_is_saved_as_spam_with_no_calls(db, monkeypatch):
    fake = ScriptedLLM(monkeypatch)
    ticket = make_ticket(db, "You won! Click http://bit.ly/x to claim your free iPhone now", "Prize")
    outcome = process_ticket(db, ticket.id)
    t = get_ticket(db, ticket.id)
    assert outcome.status == "needs_manual_reply" and outcome.llm_calls == 0 and fake.total == 0
    assert t.is_spam is True and t.category == "spam" and t.draft_reply is None


def test_manual_reply_keeps_best_draft_and_violations(db, monkeypatch):
    ScriptedLLM(monkeypatch, analysis_=analysis(category="refund_request", loss="high"), drafts=[REFUND_PROMISE])
    ticket = make_ticket(db, "I want a refund please for my broken laptop.", "Refund")
    outcome = process_ticket(db, ticket.id)
    t = get_ticket(db, ticket.id)
    assert outcome.status == "needs_manual_reply" and outcome.revision_count == 2
    assert t.revision_count == 2 and t.compliance_status == "failed"
    assert t.draft_reply and any(v["rule"] == "refund_commitment" for v in t.compliance_violations)


def test_a_ticket_cannot_be_processed_twice(db, monkeypatch):
    fake = ScriptedLLM(monkeypatch)
    ticket = make_ticket(db)
    assert process_ticket(db, ticket.id) is not None
    calls = fake.total
    assert process_ticket(db, ticket.id) is None  # status is no longer 'received'
    assert fake.total == calls


def test_unknown_ticket_returns_none(db, monkeypatch):
    ScriptedLLM(monkeypatch)
    assert process_ticket(db, 999999) is None


def test_llm_failure_ends_as_workflow_failed_and_can_be_reprocessed(db, monkeypatch):
    ScriptedLLM(monkeypatch, analysis_=FakeAPIError("quota"))
    ticket = make_ticket(db)
    outcome = process_ticket(db, ticket.id)
    assert outcome.status == "workflow_failed" and outcome.error
    assert get_ticket(db, ticket.id).status == "workflow_failed"
    runs = list_agent_runs(db, ticket.id)
    assert [(r.agent_name, r.status) for r in runs] == [("understanding", "failed")]

    # The owner presses Reprocess after the cause is fixed.
    ScriptedLLM(monkeypatch, drafts=[CLEAN_SIMPLE])
    again = process_ticket(db, ticket.id, allowed_from=REPROCESS_FROM)
    assert again.status == "awaiting_approval"
    assert get_ticket(db, ticket.id).status == "awaiting_approval"


def test_missing_policy_fails_cleanly_with_a_visible_reason(db, monkeypatch):
    ScriptedLLM(monkeypatch)
    ticket = make_ticket(db)
    monkeypatch.setattr(runner.policy_repo, "get_policy", lambda db, business_id=1: None)
    outcome = process_ticket(db, ticket.id)
    assert outcome.status == "workflow_failed" and "policy" in outcome.error.lower()
    runs = list_agent_runs(db, ticket.id)
    assert runs[-1].agent_name == "workflow" and runs[-1].status == "failed"
    assert "policy" in runs[-1].error.lower()
