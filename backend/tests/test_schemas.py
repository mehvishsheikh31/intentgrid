from datetime import datetime

import pytest
from pydantic import ValidationError

from app.schemas import (
    ContactSubmission,
    DraftUpdate,
    PolicyIn,
    TicketListItem,
    WorkflowResult,
)

VALID = {
    "name": "Asha Verma",
    "email": "asha@example.com",
    "phone": "+91 98765 43210",
    "category": "order_status",
    "subject": "Where is my order 1042?",
    "message": "I ordered a laptop last week and it has not arrived yet.",
}


def make(**changes):
    return ContactSubmission(**{**VALID, **changes})


def test_valid_payload_accepted():
    s = make()
    assert s.email == "asha@example.com"
    assert s.category == "order_status"


def test_whitespace_is_stripped():
    s = make(name="  Asha Verma  ", subject="  Hello  ")
    assert s.name == "Asha Verma"
    assert s.subject == "Hello"


def test_bad_email_rejected():
    with pytest.raises(ValidationError):
        make(email="not-an-email")


def test_empty_message_rejected():
    with pytest.raises(ValidationError):
        make(message="")
    with pytest.raises(ValidationError):
        make(message="     ")


def test_oversized_message_rejected():
    with pytest.raises(ValidationError):
        make(message="a" * 2001)


def test_message_at_limit_accepted():
    assert len(make(message="a" * 2000).message) == 2000


def test_unknown_category_rejected():
    with pytest.raises(ValidationError):
        make(category="hacking")


def test_phone_is_optional():
    data = {k: v for k, v in VALID.items() if k != "phone"}
    assert ContactSubmission(**data).phone is None
    assert make(phone="").phone is None


def test_bad_phone_rejected():
    with pytest.raises(ValidationError):
        make(phone="call me maybe")


def test_honeypot_filled_is_flagged_but_parses():
    s = make(website="http://spam.example")
    assert s.honeypot_filled is True


def test_honeypot_empty_by_default():
    assert make().honeypot_filled is False


def test_draft_update_empty_rejected():
    with pytest.raises(ValidationError):
        DraftUpdate(final_reply="   ")


def test_policy_missing_field_rejected():
    with pytest.raises(ValidationError):
        PolicyIn(business_name="TechNest", policy_text="Returns in 7 days")


def test_workflow_result_bad_status_rejected():
    with pytest.raises(ValidationError):
        WorkflowResult(ticket_id=1, status="done")


def test_workflow_result_too_many_revisions_rejected():
    with pytest.raises(ValidationError):
        WorkflowResult(ticket_id=1, status="awaiting_approval", revision_count=3)


def test_ticket_list_item_builds_and_rejects_bad_urgency():
    base = {
        "id": 1,
        "created_at": datetime.now(),
        "customer_name": "Asha",
        "subject": "Hi",
        "status": "received",
    }
    assert TicketListItem(**base).urgency_score is None
    with pytest.raises(ValidationError):
        TicketListItem(**base, urgency_score=9)
