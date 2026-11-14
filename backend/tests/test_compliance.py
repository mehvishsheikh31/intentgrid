import importlib.util
import json
from pathlib import Path

import pytest

from agents.compliance import run_compliance, should_run_llm_check
from agents.compliance_rules import blockers, build_revision_feedback, check_rules
from app.schemas import ContactSubmission
from repositories.agent_runs import list_agent_runs
from repositories.tickets import create_ticket
from workflow import llm
from workflow.schemas import DraftResult, RiskResult, UnderstandingResult
from workflow.state import new_state

_path = Path(__file__).resolve().parents[1] / "scripts" / "seed_policies.py"
_spec = importlib.util.spec_from_file_location("seed_policies", _path)
_seed = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_seed)
POLICY = _seed.load_sample_policy().policy_text

# Ten seeded violating drafts: (draft, rule that must be caught)
SEEDED = [
    ("Dear Asha, we guarantee your laptop will be fixed by tomorrow.", "guaranteed_outcome"),
    ("Dear Asha, we will refund your full amount.", "refund_commitment"),
    ("Dear Asha, it was our fault and we accept full responsibility.", "legal_admission"),
    ("Dear Asha, we can offer you compensation of ₹5,000.", "unsupported_amount"),
    ("Dear Asha, you get a 25% discount on your next order.", "unsupported_amount"),
    ("Dear Asha, your replacement will arrive within 24 hours.", "unsupported_time_commitment"),
    ("Dear Asha, track it here: https://track.example.com/abc123", "unapproved_link"),
    ("Dear Asha, you should file a lawsuit against the courier.", "legal_medical_advice"),
    ("Dear Asha, a swollen battery is perfectly safe to use.", "legal_medical_advice"),
    ("Dear Asha, that is your own fault, you stupid customer.", "abusive_language"),
]

CLEAN = [
    "Dear Asha,\n\nThank you for your message. Orders above ₹999 ship free, and delivery takes 3 to 5 business days.\n\n"
    "Warm regards,\nTechNest Support Team",
    "Dear Asha,\n\nWe are sorry for the trouble. Returns are accepted within 7 days of delivery for unused items in "
    "original packaging, and our team will review your request. We reply within one business day.\n\n"
    "Warm regards,\nTechNest Support Team",
    "Dear Asha,\n\nWe are sorry about this. As it is a safety matter, the owner will follow up with you personally. "
    "Please stop using the device for now.\n\nWarm regards,\nTechNest Support Team",
]


class FakeAPIError(Exception):
    code = 400


@pytest.fixture()
def fake_llm(monkeypatch):
    llm.reset_daily_counter()
    calls = []

    def install(output):
        def fake(prompt, system, schema):
            calls.append(prompt)
            if isinstance(output, Exception):
                raise output
            return output
        monkeypatch.setattr(llm, "_call_gemini", fake)
        return calls

    return install


def make_state(db, draft_text, category="product_inquiry", loss="low"):
    ticket = create_ticket(
        db,
        ContactSubmission(
            name="Asha Verma", email="asha@example.com", category="other",
            subject="Hello", message="placeholder message here",
        ),
    )
    state = new_state(ticket.id)
    state.update(
        customer_name="Asha Verma", customer_email="asha@example.com", customer_phone=None,
        subject="Hello", redacted_message="Where is my order?", policy_text=POLICY,
        understanding=UnderstandingResult(
            category=category, intent="x", summary="x", key_details=[], is_spam=False,
            language="en", confidence=0.9,
        ),
        risk=RiskResult(urgency_score=2, sentiment="neutral", loss_risk=loss, risk_reasons=[], escalate=False),
        draft=DraftResult(draft_reply=draft_text),
    )
    return ticket, state


def llm_json(passed=True, violations=None, feedback=""):
    return json.dumps({"passed": passed, "violations": violations or [], "revision_feedback": feedback, "layer": "llm"})


# ---------- Layer 1 rules ----------

@pytest.mark.parametrize("draft, expected_rule", SEEDED)
def test_every_seeded_violation_is_caught(draft, expected_rule):
    violations = check_rules(draft, POLICY)
    assert expected_rule in {v.rule for v in blockers(violations)}, violations


def test_seeded_catch_rate_is_100_percent():
    caught = sum(
        1 for draft, rule in SEEDED
        if rule in {v.rule for v in blockers(check_rules(draft, POLICY))}
    )
    assert caught == len(SEEDED) == 10


@pytest.mark.parametrize("draft", CLEAN)
def test_clean_drafts_have_no_blockers(draft):
    assert blockers(check_rules(draft, POLICY)) == []


def test_leaked_placeholder_and_ai_mention_are_blockers():
    rules = {v.rule for v in blockers(check_rules("Dear {{customer_name}}, as an AI language model I cannot help.", POLICY))}
    assert {"unresolved_placeholder", "internal_leak"} <= rules


def test_long_draft_and_emoji_are_warnings_only():
    text = "Dear Asha, thank you. " + "We are checking this for you. " * 40 + "😀"
    violations = check_rules(text, POLICY)
    assert {"too_long", "emoji"} <= {v.rule for v in violations}
    assert blockers(violations) == []


def test_policy_amounts_and_links_are_allowed():
    assert blockers(check_rules("The AeroBook 14 costs ₹42,999 and ships free above ₹999.", POLICY)) == []
    assert blockers(check_rules("See www.example.com", "Our site: www.example.com")) == []


def test_revision_feedback_lists_blockers_only():
    violations = check_rules("We will refund you. 😀", POLICY)
    feedback = build_revision_feedback(violations)
    assert "refund_commitment" in feedback and "emoji" not in feedback


# ---------- routing helper ----------

@pytest.mark.parametrize(
    "category, loss, expected",
    [
        ("product_inquiry", "low", False),
        ("order_status", "low", False),
        ("complaint", "low", True),
        ("refund_request", "low", True),
        ("product_inquiry", "medium", True),
        ("feedback", "high", True),
    ],
)
def test_should_run_llm_check(category, loss, expected):
    state = {
        "understanding": UnderstandingResult(category=category, intent="x", summary="x", confidence=0.5),
        "risk": RiskResult(urgency_score=2, sentiment="neutral", loss_risk=loss),
    }
    assert should_run_llm_check(state) is expected


# ---------- run_compliance ----------

def test_simple_ticket_skips_llm_layer(db, fake_llm):
    calls = fake_llm(llm_json())
    ticket, state = make_state(db, CLEAN[0])
    result = run_compliance(state, db)
    assert result.passed is True and result.layer == "rules"
    assert len(calls) == 0 and state["llm_calls"] == 0
    runs = {r.agent_name: r for r in list_agent_runs(db, ticket.id)}
    assert runs["compliance"].status == "ok" and runs["compliance"].llm_calls == 0
    assert runs["compliance_llm"].status == "skipped" and runs["compliance_llm"].error == "simple ticket"


def test_rule_failure_skips_llm_layer_even_when_risky(db, fake_llm):
    calls = fake_llm(llm_json())
    ticket, state = make_state(db, "We will refund you.", category="refund_request", loss="high")
    result = run_compliance(state, db)
    assert result.passed is False and result.layer == "rules"
    assert "refund_commitment" in result.revision_feedback
    assert len(calls) == 0
    runs = {r.agent_name: r for r in list_agent_runs(db, ticket.id)}
    assert runs["compliance_llm"].error == "rules failed"


def test_risky_ticket_runs_llm_layer_and_passes(db, fake_llm):
    calls = fake_llm(llm_json())
    ticket, state = make_state(db, CLEAN[1], category="refund_request", loss="medium")
    result = run_compliance(state, db)
    assert result.passed is True and result.layer == "llm"
    assert len(calls) == 1 and state["llm_calls"] == 1
    assert "asha@example.com" not in calls[0] and "Asha Verma" not in calls[0]
    names = [r.agent_name for r in list_agent_runs(db, ticket.id)]
    assert names == ["compliance"]


def test_llm_blocker_fails_the_draft(db, fake_llm):
    fake_llm(llm_json(
        passed=False,
        violations=[{"rule": "unsupported_promise", "severity": "blocker", "excerpt": "soon", "explanation": "Implies a repair."}],
        feedback="Do not imply a repair.",
    ))
    _, state = make_state(db, CLEAN[1], category="complaint", loss="high")
    result = run_compliance(state, db)
    assert result.passed is False
    assert "Do not imply a repair." in result.revision_feedback
    assert any(v.rule == "unsupported_promise" for v in result.violations)


def test_llm_warning_does_not_fail_and_models_passed_flag_is_ignored(db, fake_llm):
    fake_llm(llm_json(
        passed=False,
        violations=[{"rule": "tone", "severity": "warning", "excerpt": "", "explanation": "A bit cold."}],
    ))
    _, state = make_state(db, CLEAN[1], category="complaint", loss="high")
    result = run_compliance(state, db)
    assert result.passed is True
    assert [v.severity for v in result.violations] == ["warning"]


def test_llm_error_saves_failed_run_and_raises(db, fake_llm):
    fake_llm(FakeAPIError("bad"))
    ticket, state = make_state(db, CLEAN[1], category="complaint", loss="high")
    with pytest.raises(llm.LLMError):
        run_compliance(state, db)
    runs = list_agent_runs(db, ticket.id)
    assert [(r.agent_name, r.status) for r in runs] == [("compliance", "failed")]
    assert state.get("compliance") is None


def test_attempt_number_follows_revision_count(db, fake_llm):
    fake_llm(llm_json())
    ticket, state = make_state(db, CLEAN[0])
    state["revision_count"] = 2
    run_compliance(state, db)
    runs = [r for r in list_agent_runs(db, ticket.id) if r.agent_name == "compliance"]
    assert runs[0].attempt_no == 3
