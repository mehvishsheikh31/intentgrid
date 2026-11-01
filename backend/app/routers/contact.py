import hashlib

from fastapi import APIRouter, Depends, Request, status
from sqlalchemy.orm import Session

from app.db import get_db
from app.schemas import ContactSubmission
from repositories import tickets as ticket_repo

router = APIRouter(prefix="/api", tags=["contact"])


def _client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


@router.post("/contact", status_code=status.HTTP_201_CREATED)
def submit_contact(
    data: ContactSubmission,
    request: Request,
    db: Session = Depends(get_db),
):
    """Public endpoint used by the contact form on Website 1."""
    ip_hash = hashlib.sha256(_client_ip(request).encode()).hexdigest()
    ticket_repo.create_ticket(db, data, ip_hash=ip_hash)
    return {"ok": True, "message": "Thank you. We have received your message."}
