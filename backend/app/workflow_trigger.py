"""Starts the workflow in the background. Used as a FastAPI dependency so tests can replace it."""
import logging

from app.db import SessionLocal
from workflow.runner import process_ticket

logger = logging.getLogger("intentgrid.workflow")


def run_ticket_workflow(ticket_id: int, claimed: bool = False) -> None:
    """Background task. Uses its own database session and never raises."""
    db = SessionLocal()
    try:
        process_ticket(db, ticket_id, claimed=claimed)
    except Exception:
        logger.exception("Background workflow crashed for ticket %s", ticket_id)
    finally:
        db.close()


def get_workflow_starter():
    return run_ticket_workflow
