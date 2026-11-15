import pytest

from app.schemas import ContactSubmission
from llm_fakes import (
    CLEAN_RISKY, CLEAN_SIMPLE, REFUND_PROMISE, FakeAPIError, ScriptedLLM, analysis, compliance,
)
from repositories.agent_runs import list_agent_runs
from repositories.policies import upsert_policy
from repositories.tickets import create_ticket
from scripts_loader import load_sample_policy
from workflow import llm
from workflow.graph import run_workflow
from workflow.runner import build_state


def setup(db, message="Where can I see the shipping details?", subject="Shipping"):
    upsert_policy(db, load_sample_policy())
    from repositories.policies import get_policy
    ticket = create_ticket(
        db,
        ContactSubmission(
            name="Asha Verma", email="asha@example.com", category="other",
            subject=subject, message=message,
        ),
    )
    return ticket, build_state(ticket, get_policy(db))


def run_names(db, ticket):
    return [(r.agent_name, r.attempt_no, r.status) for r in list_agent_runs(db, ticket.id)]


def test_obvious_spam_makes_zero_llm_calls(db, monkeypatch):
    fake = ScriptedLLM(monkeypatch)
    ticket, state = setup(db, "Click http://bit.ly/x you won a free iPhone, claim your prize", "Prize")
    final = run_workflow(db, state)
    assert final["status"] == "needs_manual_reply"
    assert final["route"] == "spam_precheck"
    assert fake.total == 0 and final["llm_calls"] == 0
    assert final["draft"] is None
    names = {r.agent_name: r.status for r in list_agent_runs(db, ticket.id)}
    assert names == {
        "understanding": "skipped", "risk": "skipped", "responder": "skipped", "compliance": "skipped",
    }


def test_llm_detected_spam_stops_after_the_analysis_call(db, monkeypatch):
    fake = ScriptedLLM(monkeypatch, analysis_=analysis(category="other", spam=True))
    ticket, state = setup(db)
    final = run_workflow(db, state)
    assert final["status"] == "needs_manual_reply"
    assert final["llm_calls"] == 1 and fake.total == 1
    assert final["draft"] is None
    statuses = {r.agent_name: r.status for r in list_agent_runs(db, ticket.id)}
    assert statuses == {
        "understanding": "ok", "risk": "skipped", "responder": "skipped", "compliance": "skipped",
    }


def test_simple_message_makes_two_calls(db, monkeypatch):
    fake = ScriptedLLM(monkeypatch, drafts=[CLEAN_SIMPLE])
    ticket, state = setup(db)
    final = run_workflow(db, state)
    assert final["status"] == "awaiting_approval"
    assert final["route"] == "simple"
    assert final["llm_calls"] == 2 and fake.total == 2
    assert final["compliance"].layer == "rules"
    assert final["revision_count"] == 0
    assert run_names(db, ticket) == [
        ("understanding", 1, "ok"), ("risk", 1, "ok"), ("responder", 1, "ok"),
        ("compliance", 1, "ok"), ("compliance_llm", 1, "skipped"),
    ]


def test_risky_message_makes_three_calls(db, monkeypatch):
    fake = ScriptedLLM(
        monkeypatch, analysis_=analysis(category="complaint", urgency=3, loss="medium"),
        drafts=[CLEAN_RISKY],
    )
    ticket, state = setup(db, "My laptop screen flickers. Please help.", "Flicker")
    final = run_workflow(db, state)
    assert final["status"] == "awaiting_approval"
    assert final["route"] == "risky"
    assert final["llm_calls"] == 3 and fake.total == 3
    assert final["compliance"].layer == "llm"
    assert [n for n, _, _ in run_names(db, ticket)] == ["understanding", "risk", "responder", "compliance"]


def test_fails_then_passes_with_one_revision(db, monkeypatch):
    fake = ScriptedLLM(monkeypatch, drafts=[REFUND_PROMISE, CLEAN_SIMPLE])
    ticket, state = setup(db)
    final = run_workflow(db, state)
    assert final["status"] == "awaiting_approval"
    assert final["revision_count"] == 1
    assert final["llm_calls"] == 3  # analysis + 2 drafts; the rule layer costs nothing
    second_draft_prompt = [p for n, p in fake.prompts if n == "DraftResult"][1]
    assert "<compliance_feedback>" in second_draft_prompt and "refund_commitment" in second_draft_prompt
    assert "Asha" not in second_draft_prompt  # the previous draft was redacted again
    assert [(n, a) for n, a, _ in run_names(db, ticket) if n == "responder"] == [("responder", 1), ("responder", 2)]


def test_always_failing_ends_in_manual_reply_after_exactly_two_revisions(db, monkeypatch):
    fake = ScriptedLLM(
        monkeypatch, analysis_=analysis(category="refund_request", loss="high"), drafts=[REFUND_PROMISE]
    )
    ticket, state = setup(db, "I want a refund for my laptop please.", "Refund")
    final = run_workflow(db, state)
    assert final["status"] == "needs_manual_reply"
    assert final["revision_count"] == 2
    assert final["llm_calls"] == 4 and fake.counts["DraftResult"] == 3
    assert final["draft"] is not None  # the best draft and its violations are kept
    assert final["compliance"].passed is False and final["compliance"].violations


def test_worst_case_is_seven_calls(db, monkeypatch):
    fake = ScriptedLLM(
        monkeypatch, analysis_=analysis(category="complaint", loss="high"),
        drafts=[CLEAN_RISKY], compliances=[compliance(passed=False)],
    )
    ticket, state = setup(db, "My laptop is broken, this is a complaint.", "Complaint")
    final = run_workflow(db, state)
    assert final["status"] == "needs_manual_reply"
    assert final["revision_count"] == 2
    assert fake.counts == {"AnalysisResult": 1, "DraftResult": 3, "ComplianceResult": 3}
    assert final["llm_calls"] == 7


def test_state_never_allows_more_than_two_revisions(db, monkeypatch):
    ScriptedLLM(monkeypatch, drafts=[REFUND_PROMISE])
    ticket, _ = setup(db)
    from repositories.policies import get_policy
    state = build_state(ticket, get_policy(db), max_revisions=9)
    assert state["max_revisions"] == 2


def test_llm_failure_propagates_to_the_runner(db, monkeypatch):
    ScriptedLLM(monkeypatch, analysis_=FakeAPIError("bad"))
    ticket, state = setup(db)
    with pytest.raises(llm.LLMError):
        run_workflow(db, state)
    assert [(n, s) for n, _, s in run_names(db, ticket)] == [("understanding", "failed")]
