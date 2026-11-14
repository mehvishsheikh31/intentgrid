import re
import time

from sqlalchemy.orm import Session

from agents.analysis import get_or_run_analysis
from repositories.agent_runs import save_agent_run
from workflow.llm import LLMError
from workflow.schemas import RiskResult
from workflow.state import WorkflowState

AGENT_NAME = "risk"
LOSS_ORDER = {"low": 0, "medium": 1, "high": 2}

# (rule name, regex, minimum urgency, minimum loss_risk, force escalate, reason shown to owner)
# Rules can only RAISE a score. They never lower one.
BOOSTER_RULES = [
    ("legal_threat",
     r"\b(lawyers?|attorneys?|legal action|legal notice|sue|suing|court|consumer (?:court|forum|commission))\b",
     5, "high", True, "Legal threat keyword"),
    ("chargeback_fraud",
     r"\b(charge ?backs?|payment dispute|dispute the (?:charge|payment)|fraud|scam(?:med)?|cheated|cheating)\b",
     5, "high", True, "Chargeback or fraud keyword"),
    ("safety",
     r"\b(swollen|swelling|overheat(?:s|ed|ing)?|caught fire|on fire|fire|smoke|smoking|burn(?:t|ed|ing)?|exploded|explosion|sparks?)\b",
     5, "high", True, "Safety keyword"),
    ("churn_strong",
     r"\b(never again|never (?:buy|shop|order)|last time|stop buying|tell everyone|bad review|switch(?:ing)? to|worst)\b",
     4, "high", False, "Strong churn language"),
    ("cancel",
     r"\b(cancel(?:l?ed|l?ing|s)?|close my account)\b",
     3, "medium", False, "Cancel keyword"),
    ("compensation",
     r"\b(compensation|compensate)\b",
     4, "medium", True, "Compensation demand"),
]

SENTIMENT_POINTS = {"positive": 0, "neutral": 0, "negative": 5, "angry": 10}
LOSS_POINTS = {"low": 0, "medium": 10, "high": 20}


def apply_boosters(risk: RiskResult, text: str) -> tuple[RiskResult, list[str]]:
    """Raise urgency, loss_risk and escalate using fixed keyword rules."""
    urgency = risk.urgency_score
    loss = risk.loss_risk
    escalate = risk.escalate
    reasons = list(risk.risk_reasons)
    applied: list[str] = []
    for name, pattern, min_urgency, min_loss, force_escalate, reason in BOOSTER_RULES:
        if re.search(pattern, text, re.IGNORECASE):
            urgency = max(urgency, min_urgency)
            if LOSS_ORDER[min_loss] > LOSS_ORDER[loss]:
                loss = min_loss
            escalate = escalate or force_escalate
            tag = f"rule: {reason}"
            if tag not in reasons:
                reasons.append(tag)
            applied.append(name)
    boosted = risk.model_copy(
        update={
            "urgency_score": urgency,
            "loss_risk": loss,
            "escalate": escalate,
            "risk_reasons": reasons[:10],
        }
    )
    return boosted, applied


def compute_priority(risk: RiskResult) -> float:
    """Inbox sort score from 0 to 100. A heuristic, not a validated prediction."""
    score = (
        risk.urgency_score * 12
        + LOSS_POINTS[risk.loss_risk]
        + SENTIMENT_POINTS[risk.sentiment]
        + (10 if risk.escalate else 0)
    )
    return float(min(score, 100))


def run_risk(state: WorkflowState, db: Session) -> RiskResult:
    """Agent 2. Reuses the shared analysis call (no extra LLM call)."""
    start = time.perf_counter()
    calls_before = state.get("llm_calls", 0)
    try:
        base = get_or_run_analysis(state).risk
    except LLMError as exc:
        save_agent_run(
            db, ticket_id=state["ticket_id"], agent_name=AGENT_NAME, attempt_no=1,
            output_json=None, llm_calls=state.get("llm_calls", 0) - calls_before,
            duration_ms=int((time.perf_counter() - start) * 1000),
            status="failed", error=str(exc)[:500],
        )
        raise

    text = f"{state.get('subject', '')}\n{state.get('redacted_message', '')}"
    risk, applied = apply_boosters(base, text)
    priority = compute_priority(risk)

    state["risk"] = risk
    state["priority_score"] = priority
    save_agent_run(
        db, ticket_id=state["ticket_id"], agent_name=AGENT_NAME, attempt_no=1,
        output_json={**risk.model_dump(), "priority_score": priority, "rules_applied": applied},
        llm_calls=state.get("llm_calls", 0) - calls_before,
        duration_ms=int((time.perf_counter() - start) * 1000), status="ok",
    )
    return risk
