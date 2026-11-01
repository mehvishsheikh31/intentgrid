from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

InquiryCategory = Literal[
    "complaint",
    "refund_request",
    "order_status",
    "product_inquiry",
    "pricing_quote",
    "appointment_booking",
    "feedback",
    "other",
]

TicketStatus = Literal[
    "received",
    "processing",
    "awaiting_approval",
    "approved_sending",
    "sent",
    "send_failed",
    "workflow_failed",
    "needs_manual_reply",
]


class ContactSubmission(BaseModel):
    """Body of the public POST /api/contact."""

    model_config = ConfigDict(str_strip_whitespace=True)

    name: str = Field(min_length=1, max_length=120)
    email: EmailStr
    phone: str | None = Field(default=None, max_length=30, pattern=r"^[0-9+() -]{6,30}$")
    category: InquiryCategory
    subject: str = Field(min_length=1, max_length=200)
    message: str = Field(min_length=5, max_length=2000)
    # Honeypot: hidden on the form. Humans leave it empty, bots fill it.
    website: str = Field(default="", max_length=200)

    @field_validator("phone", mode="before")
    @classmethod
    def blank_phone_to_none(cls, v):
        if v is None:
            return None
        if isinstance(v, str) and not v.strip():
            return None
        return v

    @property
    def honeypot_filled(self) -> bool:
        return bool(self.website)


class TicketListItem(BaseModel):
    """One row in the inbox list."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime
    customer_name: str
    subject: str
    category: str | None = None
    urgency_score: int | None = Field(default=None, ge=1, le=5)
    loss_risk: str | None = None
    priority_score: float | None = None
    status: TicketStatus


class TicketOut(BaseModel):
    """Full ticket for the detail page."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    business_id: int = 1
    created_at: datetime
    customer_name: str
    customer_email: str
    customer_phone: str | None = None
    selected_category: str
    subject: str
    message: str
    category: str | None = None
    intent: str | None = None
    summary: str | None = None
    is_spam: bool = False
    urgency_score: int | None = Field(default=None, ge=1, le=5)
    sentiment: str | None = None
    loss_risk: str | None = None
    risk_reasons: list | None = None
    priority_score: float | None = None
    draft_reply: str | None = None
    final_reply: str | None = None
    compliance_status: str | None = None
    compliance_violations: list | None = None
    revision_count: int = 0
    status: TicketStatus
    send_error: str | None = None
    sent_at: datetime | None = None


class DraftUpdate(BaseModel):
    """Body of PATCH /api/tickets/{id}/draft (owner edits the reply)."""

    model_config = ConfigDict(str_strip_whitespace=True)

    final_reply: str = Field(min_length=1, max_length=5000)


class PolicyIn(BaseModel):
    """Body of PUT /api/policies."""

    model_config = ConfigDict(str_strip_whitespace=True)

    business_name: str = Field(min_length=1, max_length=200)
    policy_text: str = Field(min_length=1, max_length=20000)
    tone_guidelines: str = Field(min_length=1, max_length=5000)


class WorkflowResult(BaseModel):
    """What the workflow runner reports back when it finishes."""

    ticket_id: int
    status: TicketStatus
    revision_count: int = Field(default=0, ge=0, le=2)
    llm_calls: int = Field(default=0, ge=0, le=8)
    error: str | None = None


class TicketPage(BaseModel):
    """Response of GET /api/tickets: one page of the inbox."""

    items: list[TicketListItem]
    total: int = Field(ge=0)
    limit: int
    offset: int


class TicketPage(BaseModel):
    """Response of GET /api/tickets: one page of the inbox."""

    items: list[TicketListItem]
    total: int = Field(ge=0)
    limit: int
    offset: int
