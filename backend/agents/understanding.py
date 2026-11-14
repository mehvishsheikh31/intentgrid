import time

from sqlalchemy.orm import Session

from agents.analysis import get_or_run_analysis
from repositories.agent_runs import save_agent_run
from workflow.llm import LLMError
from workflow.schemas import UnderstandingResult
from workflow.state import WorkflowState

AGENT_NAME = "understanding"


def run_understanding(state: WorkflowState, db: Session) -> UnderstandingResult:
    """Agent 1. Uses the shared analysis call and saves its agent_run."""
    start = time.perf_counter()
    calls_before = state.get("llm_calls", 0)
    try:
        result = get_or_run_analysis(state).understanding
    except LLMError as exc:
        save_agent_run(
            db,
            ticket_id=state["ticket_id"],
            agent_name=AGENT_NAME,
            attempt_no=1,
            output_json=None,
            llm_calls=state.get("llm_calls", 0) - calls_before,
            duration_ms=int((time.perf_counter() - start) * 1000),
            status="failed",
            error=str(exc)[:500],
        )
        raise

    # Keep the spam flag and the spam category consistent.
    if result.is_spam or result.category == "spam":
        result = result.model_copy(update={"is_spam": True, "category": "spam"})

    state["understanding"] = result
    save_agent_run(
        db,
        ticket_id=state["ticket_id"],
        agent_name=AGENT_NAME,
        attempt_no=1,
        output_json=result.model_dump(),
        llm_calls=state.get("llm_calls", 0) - calls_before,
        duration_ms=int((time.perf_counter() - start) * 1000),
        status="ok",
    )
    return result