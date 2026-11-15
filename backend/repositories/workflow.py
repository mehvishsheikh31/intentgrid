"""Database access for the workflow runner (rule A6.13: all queries live in the repository layer)."""
from datetime import datetime, timedelta, timezone

from sqlalchemy import exists, select, update
from sqlalchemy.orm import Session

from app.models import AgentRun, Ticket
from repositories import tickets as ticket_repo

RESULT_FIELDS = {
    "category", "intent", "summary", "is_spam",
    "urgency_score", "sentiment", "loss_risk", "risk_reasons", "priority_score",
    "draft_reply", "compliance_status", "compliance_violations", "revision_count",
}


def claim_for_processing(
    db: Session,
    ticket_id: int,
    allowed_from: tuple[str, ...],
    business_id: int = 1,
    note: str | None = None,
) -> bool:
    """Atomically set status to 'processing'. Returns False if the ticket is not in an allowed
    status, so two workers can never process the same ticket at the same time.

    With a note (recovery or Reprocess), a marker row is written to agent_runs. It shows in the
    timeline and also counts as recent activity, so the stuck scan cannot pick the ticket up again."""
    result = db.execute(
        update(Ticket)
        .where(
            Ticket.id == ticket_id,
            Ticket.business_id == business_id,
            Ticket.status.in_(list(allowed_from)),
        )
        .values(status="processing")
    )
    claimed = result.rowcount == 1
    if claimed and note:
        db.add(
            AgentRun(
                ticket_id=ticket_id, business_id=business_id, agent_name="workflow", attempt_no=1,
                output_json={"note": note}, llm_calls=0, duration_ms=0, status="requeued",
            )
        )
    db.commit()
    return claimed


def save_workflow_result(
    db: Session, ticket_id: int, status: str, fields: dict, business_id: int = 1
) -> Ticket | None:
    unknown = set(fields) - RESULT_FIELDS
    if unknown:
        raise ValueError(f"Unknown ticket fields: {sorted(unknown)}")
    ticket = ticket_repo.get_ticket(db, ticket_id, business_id)
    if ticket is None:
        return None
    for key, value in fields.items():
        setattr(ticket, key, value)
    ticket.status = status
    db.commit()
    db.refresh(ticket)
    return ticket


def list_stuck_ticket_ids(
    db: Session, older_than_minutes: int = 10, limit: int = 50, business_id: int = 1
) -> list[int]:
    """Tickets in received or processing that are older than the limit AND have had no agent
    activity for that long. A ticket that is really running keeps writing agent_runs."""
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=older_than_minutes)
    recent_run = exists().where(AgentRun.ticket_id == Ticket.id, AgentRun.created_at >= cutoff)
    stmt = (
        select(Ticket.id)
        .where(
            Ticket.business_id == business_id,
            Ticket.status.in_(["received", "processing"]),
            Ticket.created_at < cutoff,
            ~recent_run,
        )
        .order_by(Ticket.id)
        .limit(limit)
    )
    return list(db.scalars(stmt))
