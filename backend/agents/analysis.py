import re
from pathlib import Path

from workflow import llm
from workflow.schemas import AnalysisResult
from workflow.state import WorkflowState

PROMPT_FILE = Path(__file__).resolve().parent / "prompts" / "analysis.md"
_TAG_RE = re.compile(r"</?\s*customer_message\s*>", re.IGNORECASE)


def load_system_prompt() -> str:
    return PROMPT_FILE.read_text(encoding="utf-8-sig")


def _clean(text: str) -> str:
    """Customer text must not be able to close or open our delimiter tags."""
    return _TAG_RE.sub("", text or "")


def build_user_prompt(state: WorkflowState) -> str:
    return (
        "Analyse the customer message below.\n"
        f"Category the customer picked on the form: {state.get('selected_category', 'unknown')}\n\n"
        "<customer_message>\n"
        f"Subject: {_clean(state.get('subject', ''))}\n\n"
        f"{_clean(state.get('redacted_message', ''))}\n"
        "</customer_message>"
    )


def get_or_run_analysis(state: WorkflowState) -> AnalysisResult:
    """The ONE shared LLM call for Agents 1 and 2. Runs once, then is reused."""
    existing = state.get("analysis")
    if existing is not None:
        return existing
    analysis = llm.generate_structured(
        build_user_prompt(state),
        AnalysisResult,
        system=load_system_prompt(),
        state=state,  # adds to state["llm_calls"]
    )
    state["analysis"] = analysis
    return analysis