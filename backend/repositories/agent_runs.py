from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import AgentRun


def save_agent_run(
    db: Session,
    ticket_id: int,
    agent_name: str,
    attempt_no: int,
    output_json: dict | None,
    llm_calls: int,
    duration_ms: int | None,
    status: str,
    error: str | None = None,
    business_id: int = 1,
) -> AgentRun:
    run = AgentRun(
        ticket_id=ticket_id,
        business_id=business_id,
        agent_name=agent_name,
        attempt_no=attempt_no,
        output_json=output_json,
        llm_calls=llm_calls,
        duration_ms=duration_ms,
        status=status,
        error=error,
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    return run


def list_agent_runs(db: Session, ticket_id: int) -> list[AgentRun]:
    stmt = select(AgentRun).where(AgentRun.ticket_id == ticket_id).order_by(AgentRun.id)
    return list(db.scalars(stmt))
