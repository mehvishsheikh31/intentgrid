import re
import time
from pathlib import Path

from sqlalchemy.orm import Session

from agents.compliance_rules import blockers, build_revision_feedback, check_rules
from repositories.agent_runs import save_agent_run
from workflow import llm
from workflow.llm import LLMError
from workflow.redact import redact
from workflow.schemas import ComplianceResult
from workflow.state import WorkflowState

AGENT_NAME = "compliance"
LLM_LAYER_NAME = "compliance_llm"
PROMPT_FILE = Path(__file__).resolve().parent / "prompts" / "compliance.md"
RISKY_CATEGORIES = {"complaint", "refund_request"}
_TAG_RE = re.compile(r"</?\s*(?:customer_message|draft_reply|policy)\s*>", re.IGNORECASE)


def load_system_prompt() -> str:
    return PROMPT_FILE.read_text(encoding="utf-8-sig")


def should_run_llm_check(state: WorkflowState) -> bool:
    """Layer 2 runs only for risky tickets: loss_risk medium or high, or complaint or refund_request."""
    risk = state.get("risk")
    understanding = state.get("understanding")
    if risk is not None and risk.loss_risk in ("medium", "high"):
        return True
    if understanding is not None and understanding.category in RISKY_CATEGORIES:
        return True
    return False


def _strip_tags(text: str) -> str:
    return _TAG_RE.sub("", text or "")


def _llm_layer(state: WorkflowState) -> ComplianceResult:
    # Personal details are redacted again before the draft goes to the LLM (rule A6.5).
    draft_text, _ = redact(
        state["draft"].draft_reply,
        name=state.get("customer_name", ""),
        email=state.get("customer_email", ""),
        phone=state.get("customer_phone"),
    )
    prompt = (
        "Review the draft reply against the policy and the customer message.\n\n"
        f"<policy>\n{state.get('policy_text', '')}\n</policy>\n\n"
        "<customer_message>\n"
        f"Subject: {_strip_tags(state.get('subject', ''))}\n\n"
        f"{_strip_tags(state.get('redacted_message', ''))}\n"
        "</customer_message>\n\n"
        f"<draft_reply>\n{_strip_tags(draft_text)}\n</draft_reply>"
    )
    return llm.generate_structured(prompt, ComplianceResult, system=load_system_prompt(), state=state)


def run_compliance(state: WorkflowState, db: Session) -> ComplianceResult:
    """Agent 4. Rules always; LLM layer only if the rules pass and the ticket is risky."""
    start = time.perf_counter()
    calls_before = state.get("llm_calls", 0)
    attempt_no = state.get("revision_count", 0) + 1
    ticket_id = state["ticket_id"]

    def ms() -> int:
        return int((time.perf_counter() - start) * 1000)

    violations = check_rules(state["draft"].draft_reply, state.get("policy_text", ""))
    layer = "rules"
    skip_reason = None
    llm_feedback = ""

    if blockers(violations):
        skip_reason = "rules failed"
    elif not should_run_llm_check(state):
        skip_reason = "simple ticket"
    else:
        try:
            llm_result = _llm_layer(state)
        except LLMError as exc:
            save_agent_run(
                db, ticket_id=ticket_id, agent_name=AGENT_NAME, attempt_no=attempt_no,
                output_json=None, llm_calls=state.get("llm_calls", 0) - calls_before,
                duration_ms=ms(), status="failed", error=str(exc)[:500],
            )
            raise
        violations = violations + llm_result.violations
        llm_feedback = llm_result.revision_feedback.strip()
        layer = "llm"

    # Only blockers fail a draft. The model's own "passed" value is ignored.
    passed = not blockers(violations)
    feedback = ""
    if not passed:
        feedback = build_revision_feedback(violations)
        if llm_feedback:
            feedback = f"{feedback}\n{llm_feedback}".strip()

    result = ComplianceResult(passed=passed, violations=violations, revision_feedback=feedback, layer=layer)
    state["compliance"] = result
    save_agent_run(
        db, ticket_id=ticket_id, agent_name=AGENT_NAME, attempt_no=attempt_no,
        output_json=result.model_dump(), llm_calls=state.get("llm_calls", 0) - calls_before,
        duration_ms=ms(), status="ok",
    )
    if skip_reason:
        save_agent_run(
            db, ticket_id=ticket_id, agent_name=LLM_LAYER_NAME, attempt_no=attempt_no,
            output_json=None, llm_calls=0, duration_ms=0, status="skipped", error=skip_reason,
        )
    return result
