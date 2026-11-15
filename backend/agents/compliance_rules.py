"""Layer 1 of Agent 4: fixed Python rules. They run for every draft and cost no LLM call.

These rules reduce risk. They are not a guarantee (rule A6.4). Owner approval stays separate.
"""
import re

from workflow.schemas import ComplianceViolation

AP = "['\u2019]"  # straight or curly apostrophe

# (rule, severity, regex, explanation)
TEXT_RULES = [
    (
        "guaranteed_outcome", "blocker",
        r"\bguarantee[ds]?\b|\bwe promise\b|\bpromise[ds]? (?:you|that|to)\b|\b100\s*%"
        r"|\bwithout (?:any )?fail\b|\bfor sure\b|\bno risk\b|\bdefinitely will\b",
        "Do not guarantee outcomes or make promises.",
    ),
    (
        "refund_commitment", "blocker",
        rf"\b(?:we|i)(?:{AP}ll| will| shall| can| are going to)\s+(?:refund|replace|reimburse|compensate)\b"
        r"|\b(?:give|offer|issue|grant|provide)\w*\s+you\s+(?:a\s+|an\s+)?(?:\w+\s+){0,2}?"
        r"(?:refund|replacement|reimbursement|compensation)s?\b"
        rf"|\byou(?:{AP}ll| will)\s+(?:receive|get)\s+(?:a\s+|an\s+|your\s+|the\s+)?(?:\w+\s+){{0,2}}?"
        r"(?:refund|replacement|reimbursement|compensation)s?\b"
        r"|\brefund (?:has been|will be|is being)\s+(?:processed|issued|credited|approved)\b",
        "Do not promise or confirm a refund, replacement or compensation. Say the team will review the request.",
    ),
    (
        "legal_admission", "blocker",
        r"\bour (?:fault|mistake|negligence)\b"
        r"|\bwe (?:are|were) (?:at fault|liable|negligent)\b"
        r"|\b(?:we|i) (?:admit|accept (?:full )?(?:responsibility|liability|blame))\b"
        r"|\bliab(?:le|ility)\b|\bnegligen\w*",
        "Do not admit fault or liability. Apologise for the inconvenience instead.",
    ),
    (
        "legal_medical_advice", "blocker",
        r"\byou (?:should|must|can|could) (?:sue|file (?:a )?(?:case|lawsuit|complaint|police|fir)"
        r"|take legal action|hire a lawyer|consult a (?:lawyer|doctor))\b"
        rf"|\b(?:is|are|it{AP}s) (?:perfectly |completely |totally )?safe to (?:use|charge|keep|continue|touch)\b"
        r"|\b(?:no|not a|not any) (?:danger|hazard)\b",
        "Do not give legal, medical or safety advice or say that something is safe.",
    ),
    (
        "abusive_language", "blocker",
        r"\b(?:idiot|stupid|moron|dumb|shut up|crap|damn|bloody|useless|pathetic|liar|lying|lied)\b"
        rf"|\byour (?:own )?fault\b|\byou(?:{AP}re| are| were) wrong\b",
        "Remove rude or blaming language. Stay polite.",
    ),
    (
        "internal_leak", "blocker",
        r"\bas an ai\b|\blanguage model\b|\bartificial intelligence\b|\bsystem prompt\b"
        r"|\binternal (?:rule|polic|guideline)\w*|\bmy instructions\b|\bcompliance check\b",
        "Never mention AI, internal rules or instructions.",
    ),
    (
        "secret_sharing", "blocker",
        r"\b(?:password|passcode|api key|secret key|otp|cvv)\s*(?:is|are|=|:)",
        "Never share passwords, keys or codes.",
    ),
    (
        "unresolved_placeholder", "blocker",
        r"\{\{.*?\}\}|\[CUSTOMER_[A-Z]+\]|\[(?:NAME|EMAIL|PHONE)\]",
        "A placeholder was left in the text. Write the final wording.",
    ),
]

DATE_RE = re.compile(
    r"\b\d{1,2}(?:st|nd|rd|th)?\s+(?:of\s+)?(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\b"
    r"|\b(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\s+\d{1,2}(?:st|nd|rd|th)?\b"
    r"|\bby (?:tomorrow|tonight|today|monday|tuesday|wednesday|thursday|friday|saturday|sunday"
    r"|end of (?:the )?(?:day|week|month))\b"
    r"|\b(?:tomorrow|tonight)\b",
    re.IGNORECASE,
)
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
PHONE_RE = re.compile(r"(?<![\w-])\+?\d[\d\s().-]{8,}\d(?!\w)")
LINK_RE = re.compile(r"https?://\S+|www\.\S+", re.IGNORECASE)
AMOUNT_RES = [
    re.compile(r"(?:₹|rs\.?|inr|\$|usd|rupees?)\s*([\d,]+(?:\.\d+)?)", re.IGNORECASE),
    re.compile(r"([\d,]+(?:\.\d+)?)\s*(?:rupees|rs\b|inr\b)", re.IGNORECASE),
]
PERCENT_RE = re.compile(r"(\d+(?:\.\d+)?)\s*%")
TIME_RE = re.compile(
    r"\b(\d+)(?:\s*(?:to|-|\u2013)\s*(\d+))?\s*(?:business\s+)?(hours?|days?|weeks?|months?)\b",
    re.IGNORECASE,
)
WORD_NUMBERS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
    "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12,
}
WORD_NUMBER_RE = re.compile(r"\b(" + "|".join(WORD_NUMBERS) + r")\b", re.IGNORECASE)
EMOJI_RE = re.compile("[\U0001F300-\U0001FAFF\u2600-\u27BF]")
MAX_WORDS = 150


def _snip(text: str, limit: int = 80) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 3] + "..."


def _amounts(text: str) -> dict[str, str]:
    found = {}
    for regex in AMOUNT_RES:
        for m in regex.finditer(text):
            digits = m.group(1).replace(",", "").rstrip(".")
            if digits:
                found[digits] = m.group(0)
    return found


def _percents(text: str) -> dict[str, str]:
    return {m.group(1): m.group(0) for m in PERCENT_RE.finditer(text)}


def _time_pairs(text: str) -> dict[tuple[str, str], str]:
    text = WORD_NUMBER_RE.sub(lambda m: str(WORD_NUMBERS[m.group(1).lower()]), text)
    found = {}
    for m in TIME_RE.finditer(text):
        unit = m.group(3).lower().rstrip("s")
        for number in (m.group(1), m.group(2)):
            if number:
                found[(number, unit)] = m.group(0)
    return found


def _digits(value: str) -> str:
    return re.sub(r"\D", "", value)


def check_rules(
    draft_text: str,
    policy_text: str = "",
    *,
    allowed_emails: tuple[str, ...] | list[str] = (),
    allowed_phones: tuple[str, ...] | list[str] = (),
) -> list[ComplianceViolation]:
    """Return every rule violation found in the draft.

    allowed_emails / allowed_phones: the customer's own details, which the draft may repeat.
    """
    violations: list[ComplianceViolation] = []
    policy_lower = policy_text.lower()

    def add(rule, severity, excerpt, explanation):
        violations.append(
            ComplianceViolation(rule=rule, severity=severity, excerpt=_snip(excerpt), explanation=explanation)
        )

    for rule, severity, pattern, explanation in TEXT_RULES:
        m = re.search(pattern, draft_text, re.IGNORECASE)
        if m:
            add(rule, severity, m.group(0), explanation)

    for link in LINK_RE.findall(draft_text):
        if link.lower().rstrip(".,)") not in policy_lower:
            add("unapproved_link", "blocker", link, "Do not include links that are not in the policy.")
            break

    ok_emails = {e.lower() for e in EMAIL_RE.findall(policy_text)} | {e.lower() for e in allowed_emails if e}
    for email in EMAIL_RE.findall(draft_text):
        if email.lower() not in ok_emails:
            add("unapproved_contact", "blocker", email,
                "Do not include email addresses that are not in the policy.")
            break
    ok_phones = {_digits(p)[-10:] for p in allowed_phones if _digits(p)}
    ok_phones |= {_digits(m.group(0))[-10:] for m in PHONE_RE.finditer(policy_text)}
    for m in PHONE_RE.finditer(draft_text):
        digits = _digits(m.group(0))
        if 10 <= len(digits) <= 15 and digits[-10:] not in ok_phones:
            add("unapproved_contact", "blocker", m.group(0),
                "Do not include phone numbers that are not in the policy.")
            break

    policy_amounts = set(_amounts(policy_text))
    for digits, shown in _amounts(draft_text).items():
        if digits not in policy_amounts:
            add("unsupported_amount", "blocker", shown,
                "This amount is not in the policy. Remove it or ask the owner to confirm.")
    policy_percents = set(_percents(policy_text))
    for number, shown in _percents(draft_text).items():
        if number not in policy_percents:
            add("unsupported_amount", "blocker", shown,
                "This percentage is not in the policy. Do not offer discounts the policy does not state.")

    policy_times = set(_time_pairs(policy_text))
    for pair, shown in _time_pairs(draft_text).items():
        if pair not in policy_times:
            add("unsupported_time_commitment", "blocker", shown,
                "This time period is not in the policy. Do not promise it.")
            break
    for m in DATE_RE.finditer(draft_text):
        if m.group(0).lower() not in policy_lower:
            add("unsupported_time_commitment", "blocker", m.group(0),
                "Do not promise a date or a day. The policy does not state it.")
            break

    words = len(draft_text.split())
    if words > MAX_WORDS:
        add("too_long", "warning", f"{words} words", f"The tone guide asks for under {MAX_WORDS} words.")
    if EMOJI_RE.search(draft_text):
        add("emoji", "warning", EMOJI_RE.search(draft_text).group(0), "The tone guide says no emojis.")
    return violations


def blockers(violations: list[ComplianceViolation]) -> list[ComplianceViolation]:
    return [v for v in violations if v.severity == "blocker"]


def build_revision_feedback(violations: list[ComplianceViolation]) -> str:
    """Short instructions for Agent 3. Only blockers are listed."""
    lines = []
    for v in blockers(violations):
        found = f' (found: "{v.excerpt}")' if v.excerpt else ""
        lines.append(f"- {v.rule}: {v.explanation}{found}")
    if not lines:
        return ""
    return "Fix these problems and keep everything else:\n" + "\n".join(lines)
