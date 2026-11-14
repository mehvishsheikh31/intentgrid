from typing import Literal, TypedDict

from workflow.schemas import (
    AnalysisResult,
    ComplianceResult,
    DraftResult,
    RiskResult,
    UnderstandingResult,
)

Route = Literal["spam_precheck", "simple", "risky"]


class WorkflowState(TypedDict, total=False):
    """Shared state passed between the router and the four agents (LangGraph)."""

    ticket_id: int
    customer_name: str
    customer_email: str
    customer_phone: str | None
    selected_category: str
    subject: str
    redacted_message: str
    policy_text: str
    tone_guidelines: str
    analysis: AnalysisResult | None
    understanding: UnderstandingResult | None
    risk: RiskResult | None
    priority_score: int | None
    draft: DraftResult | None
    compliance: ComplianceResult | None
    revision_count: int
    max_revisions: int
    route: Route | None
    llm_calls: int
    status: str
    error: str | None


def new_state(ticket_id: int, max_revisions: int = 2) -> WorkflowState:
    """A clean starting state. The runner (step 4.8) fills in the ticket fields."""
    return WorkflowState(
        ticket_id=ticket_id,
        analysis=None,
        understanding=None,
        risk=None,
        priority_score=None,
        draft=None,
        compliance=None,
        revision_count=0,
        max_revisions=max_revisions,
        route=None,
        llm_calls=0,
        status="processing",
        error=None,
    )