import hashlib

from fastapi import APIRouter, Depends, Request, status
from sqlalchemy.orm import Session

from app.db import get_db
from app.schemas import ContactSubmission
from app.security import client_ip, limiter
from repositories import tickets as ticket_repo

router = APIRouter(prefix="/api", tags=["contact"])

OK_RESPONSE = {"ok": True, "message": "Thank you. We have received your message."}


@router.post("/contact", status_code=status.HTTP_201_CREATED)
@limiter.limit("5/minute")
def submit_contact(
    data: ContactSubmission,
    request: Request,
    db: Session = Depends(get_db),
):
    """Public endpoint used by the contact form on Website 1."""
    if data.honeypot_filled:
        # A bot filled the hidden field. Look successful, store nothing.
        return OK_RESPONSE
    ip_hash = hashlib.sha256(client_ip(request).encode()).hexdigest()
    ticket_repo.create_ticket(db, data, ip_hash=ip_hash)
    return OK_RESPONSE
