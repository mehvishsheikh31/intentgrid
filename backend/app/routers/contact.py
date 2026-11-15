import hashlib

from fastapi import APIRouter, BackgroundTasks, Depends, Request, status
from sqlalchemy.orm import Session

from app.db import get_db
from app.schemas import ContactSubmission
from app.security import client_ip, limiter
from app.workflow_trigger import get_workflow_starter
from repositories import tickets as ticket_repo

router = APIRouter(prefix="/api", tags=["contact"])

OK_RESPONSE = {"ok": True, "message": "Thank you. We have received your message."}


@router.post("/contact", status_code=status.HTTP_201_CREATED)
@limiter.limit("5/minute")
def submit_contact(
    data: ContactSubmission,
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    start_workflow=Depends(get_workflow_starter),
):
    """Public endpoint used by the contact form on Website 1."""
    if data.honeypot_filled:
        # A bot filled the hidden field. Look successful, store nothing.
        return OK_RESPONSE
    ip_hash = hashlib.sha256(client_ip(request).encode()).hexdigest()
    ticket = ticket_repo.create_ticket(db, data, ip_hash=ip_hash)
    background_tasks.add_task(start_workflow, ticket.id)
    return OK_RESPONSE
