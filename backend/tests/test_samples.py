"""Step 4.11: the 12 sample messages and the run_samples.py helpers. Offline."""
import importlib.util
import json
from pathlib import Path

from app.schemas import ContactSubmission
from workflow.router import is_obvious_spam

ROOT = Path(__file__).resolve().parents[1]
SAMPLES = json.loads((ROOT / "data" / "sample_messages.json").read_text(encoding="utf-8"))

_spec = importlib.util.spec_from_file_location("run_samples", ROOT / "scripts" / "run_samples.py")
run_samples = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(run_samples)

CATEGORIES = {
    "complaint", "refund_request", "order_status", "product_inquiry", "pricing_quote",
    "appointment_booking", "feedback", "spam", "other",
}


def test_twelve_valid_messages():
    assert len(SAMPLES) == 12
    assert [m["id"] for m in SAMPLES] == list(range(1, 13))
    assert len({m["email"] for m in SAMPLES}) == 12
    for m in SAMPLES:
        ContactSubmission(
            name=m["name"], email=m["email"], phone=m["phone"], category=m["category"],
            subject=m["subject"], message=m["message"],
        )
        assert m["expected_categories"] and set(m["expected_categories"]) <= CATEGORIES


def test_the_set_covers_the_main_situations():
    labels = " ".join(m["label"] for m in SAMPLES)
    for word in ["order_status", "product", "discount", "warranty", "return", "angry", "safety",
                 "feedback", "store", "spam"]:
        assert word in labels
    spam = [m for m in SAMPLES if m["expected_categories"] == ["spam"]]
    assert len(spam) == 2
    assert sum(is_obvious_spam(m["subject"], m["message"]) for m in spam) == 1  # one pre-check, one LLM


def test_summary_averages_by_route():
    rows = [
        {"id": 1, "route": "simple", "llm_calls": 2, "status": "awaiting_approval", "complete": True},
        {"id": 2, "route": "simple", "llm_calls": 2, "status": "awaiting_approval", "complete": True},
        {"id": 3, "route": "risky", "llm_calls": 3, "status": "awaiting_approval", "complete": True},
        {"id": 4, "route": "risky", "llm_calls": 7, "status": "needs_manual_reply", "complete": True},
        {"id": 5, "route": "spam_precheck", "llm_calls": 0, "status": "needs_manual_reply", "complete": True},
        {"id": 6, "route": "failed", "llm_calls": 1, "status": "workflow_failed", "complete": False},
    ]
    s = run_samples.summarize(rows)
    assert s["messages"] == 6 and s["total_calls"] == 15 and s["average_calls"] == 2.5
    assert s["max_calls"] == 7
    assert s["by_route"]["simple"] == {"messages": 2, "average_calls": 2.0, "max_calls": 2}
    assert s["by_route"]["risky"] == {"messages": 2, "average_calls": 5.0, "max_calls": 7}
    assert s["by_route"]["spam_precheck"]["average_calls"] == 0
    assert s["failed"] == [6] and s["incomplete"] == [6]


def test_summary_of_nothing_does_not_crash():
    assert run_samples.summarize([])["average_calls"] == 0
