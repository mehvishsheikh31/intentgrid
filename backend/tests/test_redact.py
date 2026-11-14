from workflow.redact import redact, restore

NAME = "Rahul Sharma"
EMAIL = "rahul.sharma@example.com"
PHONE = "+91 98765 43210"


def test_round_trip_and_order_number_kept():
    text = f"Hi, I am {NAME}. Email {EMAIL}, call {PHONE}. Order 1042 is late."
    red, mapping = redact(text, name=NAME, email=EMAIL, phone=PHONE)
    assert NAME not in red
    assert EMAIL not in red
    assert "98765" not in red
    assert "1042" in red
    assert restore(red, mapping) == text


def test_first_name_only_is_redacted():
    red, _ = redact("Hello, this is Rahul.", name=NAME, email=EMAIL)
    assert "Rahul" not in red
    assert "[CUSTOMER_NAME]" in red


def test_other_email_and_phone_are_redacted():
    red, _ = redact(
        "Contact my friend a@b.com or 99999 88888.", name=NAME, email=EMAIL
    )
    assert "a@b.com" not in red
    assert "99999" not in red
    assert "[EMAIL]" in red
    assert "[PHONE]" in red


def test_no_phone_given():
    _, mapping = redact("Hello", name=NAME, email=EMAIL, phone=None)
    assert "[CUSTOMER_PHONE]" not in mapping


def test_restore_fills_draft_placeholders():
    _, mapping = redact("x", name=NAME, email=EMAIL)
    assert restore("Dear [CUSTOMER_NAME],", mapping) == "Dear Rahul Sharma,"