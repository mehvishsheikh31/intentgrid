"""Runs the workflow for one ticket and saves the result to the database."""
import logging
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.config import settings
from integrations.discord import maybe_alert
from repositories import policies as policy_repo
from repositories import tickets as ticket_repo
from repositories import workflow as workflow_repo
from repositories.agent_runs import save_agent_run
from workflow.graph import run_workflow
from workflow.llm import LLMError
from workflow.redact import redact
from workflow.state import WorkflowState, new_state

logger = logging.getLogger("intentgrid.workflow")

NEW_TICKET = ("received",)
REPROCESS_FROM = ("workflow_failed", "needs_manual_reply")
HARD_MAX_REVISIONS = 2  # rule A6.3: never more than 2


class WorkflowConfigError(Exception):
    """Something the owner must fix, for example: no policy has been saved."""


@dataclass
class WorkflowOutcome:
    ticket_id: int
    status: str
    revision_count: int = 0
    llm_calls: int = 0
    error: str | None = None
    route: str | None = None


def build_state(ticket, policy, max_revisions: int | None = None) -> WorkflowState:
    """Personal details are redacted here, before any text can reach an LLM (rule A6.5)."""
    ident = {"name": ticket.customer_name, "email": ticket.customer_email, "phone": ticket.customer_phone}
    limit = settings.max_revisions if max_revisions is None else max_revisions
    state = new_state(ticket.id, max_revisions=max(0, min(limit, HARD_MAX_REVISIONS)))
    state.update(
        customer_name=ticket.customer_name,
        customer_email=ticket.customer_email,
        customer_phone=ticket.customer_phone,
        selected_category=ticket.selected_category,
        subject=redact(ticket.subject, **ident)[0],
        redacted_message=redact(ticket.message, **ident)[0],
        policy_text=policy.policy_text,
        tone_guidelines=policy.tone_guidelines,
    )
    return state


def ticket_fields(state: WorkflowState) -> dict:
    """Turn the final workflow state into the ticket columns."""
    fields: dict = {"revision_count": state.get("revision_count", 0)}
    if state.get("route") == "spam_precheck":
        fields.update(category="spam", is_spam=True)
    understanding = state.get("understanding")
    if understanding is not None:
        fields.update(
            category=understanding.category, intent=understanding.intent,
            summary=understanding.summary, is_spam=understanding.is_spam,
        )
    risk = state.get("risk")
    if risk is not None:
        fields.update(
            urgency_score=risk.urgency_score, sentiment=risk.sentiment, loss_risk=risk.loss_risk,
            risk_reasons=list(risk.risk_reasons), priority_score=state.get("priority_score"),
        )
    draft = state.get("draft")
    if draft is not None:
        fields["draft_reply"] = draft.draft_reply
    compliance = state.get("compliance")
    if compliance is not None:
        fields.update(
            compliance_status="passed" if compliance.passed else "failed",
            compliance_violations=[v.model_dump() for v in compliance.violations],
        )
    return fields


def process_ticket(
    db: Session,
    ticket_id: int,
    *,
    allowed_from: tuple[str, ...] = NEW_TICKET,
    claimed: bool = False,
    business_id: int = 1,
) -> WorkflowOutcome | None:
    """Process one ticket. Returns None if the ticket could not be claimed (already taken).
    Never raises for workflow problems: they end as status workflow_failed."""
    if not claimed and not workflow_repo.claim_for_processing(db, ticket_id, allowed_from, business_id):
        return None
    ticket = ticket_repo.get_ticket(db, ticket_id, business_id)
    if ticket is None:
        return None

    try:
        policy = policy_repo.get_policy(db, business_id)
        if policy is None:
            raise WorkflowConfigError("No policy saved yet. Save the business policy first.")
        state = build_state(ticket, policy)
        final = run_workflow(db, state)
        status = final.get("status", "workflow_failed")
        if status not in ("awaiting_approval", "needs_manual_reply"):
            status = "workflow_failed"
        workflow_repo.save_workflow_result(db, ticket_id, status, ticket_fields(final), business_id)
        maybe_alert(db, ticket_id, business_id)  # never raises; the ticket is already saved
        return WorkflowOutcome(
            ticket_id=ticket_id, status=status,
            revision_count=final.get("revision_count", 0), llm_calls=final.get("llm_calls", 0),
            route=final.get("route"),
        )
    except Exception as exc:
        logger.exception("Workflow failed for ticket %s", ticket_id)
        db.rollback()
        message = str(exc)[:500]
        if not isinstance(exc, LLMError):  # agents already record their own LLM failures
            save_agent_run(
                db, ticket_id=ticket_id, agent_name="workflow", attempt_no=1, output_json=None,
                llm_calls=0, duration_ms=None, status="failed", error=message, business_id=business_id,
            )
        workflow_repo.save_workflow_result(db, ticket_id, "workflow_failed", {}, business_id)
        return WorkflowOutcome(ticket_id=ticket_id, status="workflow_failed", error=message)
