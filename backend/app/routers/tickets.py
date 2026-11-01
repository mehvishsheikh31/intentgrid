from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.db import get_db
from app.schemas import DraftUpdate, TicketOut, TicketPage, TicketStatus
from repositories import tickets as ticket_repo

router = APIRouter(prefix="/api/tickets", tags=["tickets"])

LOCKED_STATUSES = {"approved_sending", "sent"}


@router.get("", response_model=TicketPage)
def list_tickets(
    status: list[TicketStatus] | None = Query(default=None),
    category: str | None = None,
    q: str | None = Query(default=None, max_length=100),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    items, total = ticket_repo.list_tickets(
        db, statuses=status, category=category, q=q, limit=limit, offset=offset
    )
    return TicketPage(items=items, total=total, limit=limit, offset=offset)


@router.get("/{ticket_id}", response_model=TicketOut)
def get_ticket(ticket_id: int, db: Session = Depends(get_db)):
    ticket = ticket_repo.get_ticket(db, ticket_id)
    if ticket is None:
        raise HTTPException(status_code=404, detail="Ticket not found")
    return ticket


@router.patch("/{ticket_id}/draft", response_model=TicketOut)
def edit_draft(ticket_id: int, body: DraftUpdate, db: Session = Depends(get_db)):
    ticket = ticket_repo.get_ticket(db, ticket_id)
    if ticket is None:
        raise HTTPException(status_code=404, detail="Ticket not found")
    if ticket.status in LOCKED_STATUSES:
        raise HTTPException(status_code=409, detail="This reply is already sent or sending")
    return ticket_repo.update_draft(db, ticket_id, body.final_reply)


@router.post("/{ticket_id}/approve", status_code=501)
def approve_ticket(ticket_id: int):
    """Stub. Real approval and Gmail sending arrive in Phase 7."""
    return {"detail": "Not implemented yet"}
