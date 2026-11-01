from datetime import datetime, timezone

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.models import Ticket
from app.schemas import ContactSubmission


def create_ticket(
    db: Session,
    data: ContactSubmission,
    ip_hash: str | None = None,
    business_id: int = 1,
) -> Ticket:
    ticket = Ticket(
        business_id=business_id,
        customer_name=data.name,
        customer_email=data.email,
        customer_phone=data.phone,
        selected_category=data.category,
        subject=data.subject,
        message=data.message,
        status="received",
        ip_hash=ip_hash,
    )
    db.add(ticket)
    db.commit()
    db.refresh(ticket)
    return ticket


def get_ticket(db: Session, ticket_id: int, business_id: int = 1) -> Ticket | None:
    return db.scalar(
        select(Ticket).where(Ticket.id == ticket_id, Ticket.business_id == business_id)
    )


def _escape_like(text: str) -> str:
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def list_tickets(
    db: Session,
    *,
    statuses: list[str] | None = None,
    category: str | None = None,
    q: str | None = None,
    limit: int = 50,
    offset: int = 0,
    business_id: int = 1,
) -> tuple[list[Ticket], int]:
    """Return (tickets, total). Highest priority first; unscored tickets last."""
    limit = max(1, min(limit, 100))
    offset = max(0, offset)

    conditions = [Ticket.business_id == business_id]
    if statuses:
        conditions.append(Ticket.status.in_(statuses))
    if category:
        conditions.append(Ticket.category == category)
    if q and q.strip():
        like = f"%{_escape_like(q.strip())}%"
        conditions.append(
            or_(
                Ticket.subject.ilike(like, escape="\\"),
                Ticket.message.ilike(like, escape="\\"),
                Ticket.customer_name.ilike(like, escape="\\"),
                Ticket.customer_email.ilike(like, escape="\\"),
            )
        )

    total = db.scalar(select(func.count()).select_from(Ticket).where(*conditions)) or 0
    stmt = (
        select(Ticket)
        .where(*conditions)
        .order_by(
            Ticket.priority_score.desc().nulls_last(),
            Ticket.created_at.desc(),
            Ticket.id.desc(),
        )
        .limit(limit)
        .offset(offset)
    )
    return list(db.scalars(stmt)), total


def update_draft(
    db: Session, ticket_id: int, final_reply: str, business_id: int = 1
) -> Ticket | None:
    ticket = get_ticket(db, ticket_id, business_id)
    if ticket is None:
        return None
    ticket.final_reply = final_reply
    # The owner fixed a ticket that needed a manual reply: it can now be approved.
    if ticket.status == "needs_manual_reply":
        ticket.status = "awaiting_approval"
    db.commit()
    db.refresh(ticket)
    return ticket


def set_status(
    db: Session,
    ticket_id: int,
    status: str,
    send_error: str | None = None,
    business_id: int = 1,
) -> Ticket | None:
    ticket = get_ticket(db, ticket_id, business_id)
    if ticket is None:
        return None
    ticket.status = status
    ticket.send_error = send_error
    if status == "sent":
        ticket.sent_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(ticket)
    return ticket
