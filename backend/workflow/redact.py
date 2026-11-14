import re

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
PHONE_RE = re.compile(r"(?<!\w)\+?\d[\d\s().-]{8,}\d(?!\w)")


def _digits(value: str) -> str:
    return re.sub(r"\D", "", value)


def redact(
    text: str, *, name: str, email: str, phone: str | None = None
) -> tuple[str, dict[str, str]]:
    """Swap the customer's name, email and phone for placeholders.

    Any other email or phone number in the text becomes [EMAIL] / [PHONE].
    Returns (redacted_text, mapping). Use restore() with the mapping.
    """
    mapping = {"[CUSTOMER_NAME]": name, "[CUSTOMER_EMAIL]": email}
    if phone:
        mapping["[CUSTOMER_PHONE]"] = phone

    out = text

    def email_sub(m: re.Match) -> str:
        return "[CUSTOMER_EMAIL]" if m.group(0).lower() == email.lower() else "[EMAIL]"

    out = EMAIL_RE.sub(email_sub, out)

    customer_digits = _digits(phone) if phone else ""

    def phone_sub(m: re.Match) -> str:
        digits = _digits(m.group(0))
        if not 10 <= len(digits) <= 15:
            return m.group(0)  # not a phone number (order numbers etc.)
        if customer_digits and digits[-10:] == customer_digits[-10:]:
            return "[CUSTOMER_PHONE]"
        return "[PHONE]"

    out = PHONE_RE.sub(phone_sub, out)

    parts = [p for p in name.split() if len(p) >= 3]
    options = sorted({name.strip(), *parts}, key=len, reverse=True)
    options = [o for o in options if o]
    if options:
        pattern = r"(?<!\w)(?:" + "|".join(re.escape(o) for o in options) + r")(?!\w)"
        out = re.sub(pattern, "[CUSTOMER_NAME]", out, flags=re.IGNORECASE)

    return out, mapping


def restore(text: str, mapping: dict[str, str]) -> str:
    """Put the real values back for the placeholders in the mapping."""
    for placeholder, value in mapping.items():
        text = text.replace(placeholder, value)
    return text