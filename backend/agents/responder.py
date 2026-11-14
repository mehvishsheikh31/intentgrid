import re
import time
from pathlib import Path

from sqlalchemy.orm import Session

from agents.analysis import _clean
from repositories.agent_runs import save_agent_run
from workflow import llm
from workflow.llm import LLMError
from workflow.redact import redact, restore
from workflow.schemas import DraftResult
from workflow.state import WorkflowState

AGENT_NAME = "responder"
PROMPT_FILE = Path(__file__).resolve().parent / "prompts" / "responder.md"
NAME_PLACEHOLDER_RE = re.compile(r"\{\{\s*customer_name\s*\}\}", re.IGNORECASE)


def load_system_prompt() -> str:
    return PROMPT_FILE.read_text(encoding="utf-8-sig")


def _identity(state: WorkflowState) -> dict:
    return {
        "name": state.get("customer_name", ""),
        "email": state.get("customer_email", ""),
        "phone": state.get("customer_phone"),
    }


def build_user_prompt(state: WorkflowState) -> str:
    u = state["understanding"]
    r = state["risk"]
    parts = [
        "Write a reply to the customer message below.",
        f"<policy>\n{state.get('policy_text', '')}\n</policy>",
        f"<tone_guidelines>\n{state.get('tone_guidelines', '')}\n</tone_guidelines>",
        "<analysis>\n"
        f"Category: {u.category}\n"
        f"Intent: {u.intent}\n"
        f"Summary: {u.summary}\n"
        f"Key details: {', '.join(u.key_details) or 'none'}\n"
        f"Urgency (1-5): {r.urgency_score}\n"
        f"Sentiment: {r.sentiment}\n"
        f"Loss risk: {r.loss_risk}\n"
        f"Escalate to owner: {r.escalate}\n"
        "</analysis>",
        "<customer_message>\n"
        f"Subject: {_clean(state.get('subject', ''))}\n\n"
        f"{_clean(state.get('redacted_message', ''))}\n"
        "</customer_message>",
    ]
    previous = state.get("draft")
    compliance = state.get("compliance")
    if previous is not None and compliance is not None and not compliance.passed:
        previous_text, _ = redact(previous.draft_reply, **_identity(state))
        parts.append(f"<previous_draft>\n{previous_text}\n</previous_draft>")
        parts.append(
            f"<compliance_feedback>\n{compliance.revision_feedback}\n</compliance_feedback>\n"
            "Revise the previous draft and fix every problem in the feedback."
        )
    return "\n\n".join(parts)


def finalize_text(text: str, state: WorkflowState) -> str:
    """Code (not the model) puts the real customer details back."""
    ident = _identity(state)
    name = ident["name"]
    text = NAME_PLACEHOLDER_RE.sub(lambda m: name, text)
    mapping = {"[CUSTOMER_NAME]": name, "[CUSTOMER_EMAIL]": ident["email"]}
    if ident["phone"]:
        mapping["[CUSTOMER_PHONE]"] = ident["phone"]
    return restore(text, mapping)


def run_responder(state: WorkflowState, db: Session) -> DraftResult:
    """Agent 3. Writes the first draft, or a revision when compliance feedback exists."""
    start = time.perf_counter()
    calls_before = state.get("llm_calls", 0)
    attempt_no = state.get("revision_count", 0) + 1
    try:
        draft = llm.generate_structured(
            build_user_prompt(state), DraftResult,
            system=load_system_prompt(), state=state,
        )
    except LLMError as exc:
        save_agent_run(
            db, ticket_id=state["ticket_id"], agent_name=AGENT_NAME, attempt_no=attempt_no,
            output_json=None, llm_calls=state.get("llm_calls", 0) - calls_before,
            duration_ms=int((time.perf_counter() - start) * 1000),
            status="failed", error=str(exc)[:500],
        )
        raise

    draft = draft.model_copy(update={"draft_reply": finalize_text(draft.draft_reply, state)})
    state["draft"] = draft
    save_agent_run(
        db, ticket_id=state["ticket_id"], agent_name=AGENT_NAME, attempt_no=attempt_no,
        output_json=draft.model_dump(), llm_calls=state.get("llm_calls", 0) - calls_before,
        duration_ms=int((time.perf_counter() - start) * 1000), status="ok",
    )
    return draft
