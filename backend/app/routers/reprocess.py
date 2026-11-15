from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db import get_db
from app.workflow_trigger import get_workflow_starter
from repositories import tickets as ticket_repo
from repositories import workflow as workflow_repo
from workflow.runner import REPROCESS_FROM

router = APIRouter(prefix="/api/tickets", tags=["workflow"])


@router.post("/{ticket_id}/reprocess", status_code=202)
def reprocess_ticket(
    ticket_id: int,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    start_workflow=Depends(get_workflow_starter),
):
    """Owner button: run the agents again for a failed or manual-reply ticket."""
    ticket = ticket_repo.get_ticket(db, ticket_id)
    if ticket is None:
        raise HTTPException(status_code=404, detail="Ticket not found")
    if ticket.status not in REPROCESS_FROM or not workflow_repo.claim_for_processing(
        db, ticket_id, REPROCESS_FROM, note="Owner pressed Reprocess"
    ):
        raise HTTPException(
            status_code=409, detail="Only failed or manual-reply tickets can be reprocessed"
        )
    background_tasks.add_task(start_workflow, ticket_id, claimed=True)
    return {"ticket_id": ticket_id, "status": "processing"}
