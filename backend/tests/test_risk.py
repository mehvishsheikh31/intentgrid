import itertools
import json

import pytest

from agents.risk import apply_boosters, compute_priority, run_risk
from agents.understanding import run_understanding
from app.schemas import ContactSubmission
from repositories.agent_runs import list_agent_runs
from repositories.tickets import create_ticket
from workflow import llm
from workflow.schemas import RiskResult
from workflow.state import new_state


def risk(urgency=2, sentiment="neutral", loss="low", escalate=False, reasons=None):
    return RiskResult(
        urgency_score=urgency, sentiment=sentiment, loss_risk=loss,
        risk_reasons=reasons or [], escalate=escalate,
    )


def analysis_json(urgency=2, loss="low", sentiment="neutral"):
    return json.dumps({
        "understanding": {
            "category": "refund_request", "intent": "Wants a refund",
            "summary": "Laptop failed; wants a refund.", "key_details": [],
            "is_spam": False, "language": "en", "confidence": 0.9,
        },
        "risk": {
            "urgency_score": urgency, "sentiment": sentiment, "loss_risk": loss,
            "risk_reasons": ["model reason"], "escalate": False,
        },
    })


@pytest.fixture()
def fake_llm(monkeypatch):
    llm.reset_daily_counter()
    calls = []

    def install(output):
        def fake(prompt, system, schema):
            calls.append(prompt)
            return output
        monkeypatch.setattr(llm, "_call_gemini", fake)
        return calls

    return install


def make_state(db, message):
    ticket = create_ticket(
        db,
        ContactSubmission(
            name="Asha Verma", email="asha@example.com", category="refund_request",
            subject="Problem", message="placeholder message here",
        ),
    )
    state = new_state(ticket.id)
    state.update(selected_category="refund_request", subject="Problem", redacted_message=message)
    return ticket, state


@pytest.mark.parametrize(
    "text, rule_reason",
    [
        ("I will call my lawyer tomorrow", "Legal threat"),
        ("I will do a chargeback with my bank", "Chargeback or fraud"),
        ("This is fraud, you cheated me", "Chargeback or fraud"),
        ("The battery is swollen and smoking", "Safety"),
        ("I will never again buy from you", "Strong churn"),
        ("Please cancel my order", "Cancel keyword"),
    ],
)
def test_boosters_raise_scores(text, rule_reason):
    boosted, applied = apply_boosters(risk(urgency=1, loss="low"), text)
    assert applied
    assert any(rule_reason in r for r in boosted.risk_reasons)
    assert boosted.urgency_score >= 3
    assert boosted.loss_risk in ("medium", "high")


def test_legal_threat_forces_top_scores_and_escalation():
    boosted, _ = apply_boosters(risk(urgency=1), "I am calling my lawyer")
    assert boosted.urgency_score == 5
    assert boosted.loss_risk == "high"
    assert boosted.escalate is True


def test_no_keyword_means_no_change():
    base = risk(urgency=2, loss="low")
    boosted, applied = apply_boosters(base, "Does the Zenith X1 come in blue?")
    assert applied == []
    assert boosted == base


def test_rules_never_lower_a_score():
    texts = ["", "hello", "cancel my order", "lawyer chargeback fire", "never again"]
    for u, loss, esc, text in itertools.product(
        range(1, 6), ["low", "medium", "high"], [False, True], texts
    ):
        base = risk(urgency=u, loss=loss, escalate=esc)
        boosted, _ = apply_boosters(base, text)
        order = {"low": 0, "medium": 1, "high": 2}
        assert boosted.urgency_score >= base.urgency_score
        assert order[boosted.loss_risk] >= order[base.loss_risk]
        assert boosted.escalate or not base.escalate
        assert boosted.sentiment == base.sentiment


def test_priority_score_range_and_order():
    low = compute_priority(risk(urgency=1, sentiment="positive", loss="low"))
    mid = compute_priority(risk(urgency=3, sentiment="negative", loss="medium"))
    top = compute_priority(risk(urgency=5, sentiment="angry", loss="high", escalate=True))
    assert 0 <= low < mid < top <= 100
    assert top == 100


def test_angry_refund_threat_scores_high_via_run_risk(db, fake_llm):
    # Even if the model scored it low, the rules must lift it (spec: urgency 4+, loss high).
    fake_llm(analysis_json(urgency=2, loss="low", sentiment="angry"))
    ticket, state = make_state(
        db, "Refund me today or I will do a chargeback. Worst service ever."
    )
    result = run_risk(state, db)
    assert result.urgency_score >= 4
    assert result.loss_risk == "high"
    assert state["priority_score"] >= 70


def test_agents_one_and_two_share_one_llm_call(db, fake_llm):
    calls = fake_llm(analysis_json())
    ticket, state = make_state(db, "My laptop stopped working after 3 days.")
    run_understanding(state, db)
    run_risk(state, db)
    assert len(calls) == 1
    assert state["llm_calls"] == 1
    runs = {r.agent_name: r for r in list_agent_runs(db, ticket.id)}
    assert runs["understanding"].llm_calls == 1
    assert runs["risk"].llm_calls == 0
    assert runs["risk"].status == "ok"
    assert "priority_score" in runs["risk"].output_json
