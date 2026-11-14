import pytest
from pydantic import ValidationError

from workflow.schemas import (
    AnalysisResult,
    ComplianceResult,
    ComplianceViolation,
    DraftResult,
    RiskResult,
    UnderstandingResult,
)
from workflow.state import new_state


def good_understanding(**over):
    data = dict(
        category="refund_request",
        intent="Customer wants a refund for a faulty laptop",
        summary="Laptop stopped working after 3 days; customer asks for a refund.",
        key_details=["order 1042"],
        is_spam=False,
        language="en",
        confidence=0.9,
    )
    data.update(over)
    return data


def good_risk(**over):
    data = dict(
        urgency_score=4,
        sentiment="angry",
        loss_risk="high",
        risk_reasons=["threatens chargeback"],
        escalate=True,
    )
    data.update(over)
    return data


def test_understanding_builds():
    assert UnderstandingResult(**good_understanding()).category == "refund_request"


def test_invalid_category_rejected():
    with pytest.raises(ValidationError):
        UnderstandingResult(**good_understanding(category="banana"))


def test_confidence_out_of_range_rejected():
    with pytest.raises(ValidationError):
        UnderstandingResult(**good_understanding(confidence=1.5))


def test_summary_over_40_words_rejected():
    with pytest.raises(ValidationError):
        UnderstandingResult(**good_understanding(summary="word " * 41))


@pytest.mark.parametrize("bad", [0, 6, 9])
def test_urgency_out_of_range_rejected(bad):
    with pytest.raises(ValidationError):
        RiskResult(**good_risk(urgency_score=bad))


def test_invalid_sentiment_and_loss_risk_rejected():
    with pytest.raises(ValidationError):
        RiskResult(**good_risk(sentiment="furious"))
    with pytest.raises(ValidationError):
        RiskResult(**good_risk(loss_risk="extreme"))


def test_analysis_result_splits_into_two_results():
    analysis = AnalysisResult(
        understanding=good_understanding(), risk=good_risk()
    )
    u, r = analysis.split()
    assert isinstance(u, UnderstandingResult)
    assert isinstance(r, RiskResult)
    assert r.urgency_score == 4


def test_analysis_result_needs_both_parts():
    with pytest.raises(ValidationError):
        AnalysisResult(understanding=good_understanding())


def test_draft_and_compliance_models():
    d = DraftResult(draft_reply="Hi {{customer_name}}, ...")
    assert d.open_items == []
    v = ComplianceViolation(rule="guaranteed_outcome", severity="blocker")
    c = ComplianceResult(passed=False, violations=[v], layer="rules")
    assert c.violations[0].severity == "blocker"


def test_invalid_violation_severity_rejected():
    with pytest.raises(ValidationError):
        ComplianceViolation(rule="x", severity="critical")


def test_new_state_defaults():
    s = new_state(7)
    assert s["ticket_id"] == 7
    assert s["llm_calls"] == 0
    assert s["revision_count"] == 0
    assert s["max_revisions"] == 2
    assert s["route"] is None