"""The code-only router (rule A6.14). Plain Python. It never calls the LLM and is not an agent.

It only chooses the path: the spam pre-check, the spam stop, whether the Agent 4 LLM check
runs, and what happens after compliance. It can never skip Layer 1 rules or owner approval.
"""
import re

from agents.compliance import should_run_llm_check
from workflow.state import WorkflowState

LINK_RE = re.compile(r"https?://\S+|www\.\S+", re.IGNORECASE)

# Specific phrases only. Normal shop words such as "free shipping" must not be here.
SPAM_PHRASES = [
    "you have won", "you've won", "you won", "claim your", "click here", "click the link",
    "free iphone", "free gift", "lottery", "jackpot", "crypto", "bitcoin",
    "investment opportunity", "earn money", "work from home", "make money",
    "limited time offer", "act now", "viagra", "casino", "loan approved",
    "100% free", "bit.ly", "tinyurl",
]


def spam_signals(subject: str, message: str) -> tuple[int, int]:
    """Return (number of links, number of distinct spam phrases)."""
    text = f"{subject}\n{message}".lower()
    links = len(LINK_RE.findall(text))
    phrases = sum(1 for p in SPAM_PHRASES if p in text)
    return links, phrases


def is_obvious_spam(subject: str, message: str) -> bool:
    """Pre-check before any LLM call. Only OBVIOUS spam: 3+ links, 2+ spam phrases, or a link plus a phrase."""
    links, phrases = spam_signals(subject, message)
    return links >= 3 or phrases >= 2 or (links >= 1 and phrases >= 1)


def decide_route(state: WorkflowState) -> str:
    """'risky' means the Agent 4 LLM check will run. Layer 1 rules run either way."""
    return "risky" if should_run_llm_check(state) else "simple"


# ---- conditional edges used by the LangGraph graph ----

def route_after_precheck(state: WorkflowState) -> str:
    return "spam" if state.get("route") == "spam_precheck" else "analyse"


def route_after_understanding(state: WorkflowState) -> str:
    understanding = state.get("understanding")
    return "spam" if understanding is not None and understanding.is_spam else "continue"


def route_after_compliance(state: WorkflowState) -> str:
    """pass: draft is fine. revise: go back to Agent 3. exhausted: needs_manual_reply."""
    if state["compliance"].passed:
        return "pass"
    if state.get("revision_count", 0) < state.get("max_revisions", 2):
        return "revise"
    return "exhausted"
