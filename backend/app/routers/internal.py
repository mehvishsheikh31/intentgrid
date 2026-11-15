from fastapi import APIRouter, BackgroundTasks, Depends, Query
from sqlalchemy.orm import Session

from app.db import get_db
from app.workflow_trigger import get_workflow_starter
from repositories import workflow as workflow_repo

router = APIRouter(prefix="/api/internal", tags=["internal"])


@router.post("/reprocess-stuck")
def reprocess_stuck(
    background_tasks: BackgroundTasks,
    minutes: int = Query(default=10, ge=1, le=1440),
    db: Session = Depends(get_db),
    start_workflow=Depends(get_workflow_starter),
):
    """Re-queue tickets stuck in received or processing, for example after a Render restart."""
    requeued = []
    for ticket_id in workflow_repo.list_stuck_ticket_ids(db, older_than_minutes=minutes):
        if workflow_repo.claim_for_processing(
            db, ticket_id, ("received", "processing"), note="Re-queued after being stuck"
        ):
            background_tasks.add_task(start_workflow, ticket_id, claimed=True)
            requeued.append(ticket_id)
    return {"requeued": requeued, "count": len(requeued)}
