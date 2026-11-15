"""Shared fake Gemini for the workflow tests. No real calls, no quota."""
import json

from workflow import llm

REFUND_PROMISE = "Dear {{customer_name}}, we will refund you in full. Warm regards, TechNest Support Team"
CLEAN_SIMPLE = (
    "Dear {{customer_name}},\n\nThank you for your message. Orders above ₹999 ship free, "
    "with delivery in 3 to 5 business days.\n\nWarm regards,\nTechNest Support Team"
)
CLEAN_RISKY = (
    "Dear {{customer_name}},\n\nWe are sorry for the trouble. Our team will review your request "
    "and reply within one business day.\n\nWarm regards,\nTechNest Support Team"
)


def analysis(category="product_inquiry", urgency=2, loss="low", sentiment="neutral", spam=False):
    return {
        "understanding": {
            "category": category, "intent": "Customer asks something", "summary": "A short summary.",
            "key_details": [], "is_spam": spam, "language": "en", "confidence": 0.9,
        },
        "risk": {
            "urgency_score": urgency, "sentiment": sentiment, "loss_risk": loss,
            "risk_reasons": ["model reason"], "escalate": False,
        },
    }


def draft(text):
    return {"draft_reply": text, "policies_used": ["Shipping"], "open_items": []}


def compliance(passed=True):
    if passed:
        return {"passed": True, "violations": [], "revision_feedback": "", "layer": "llm"}
    return {
        "passed": False,
        "violations": [{"rule": "unsupported_promise", "severity": "blocker",
                        "excerpt": "soon", "explanation": "Implies a repair."}],
        "revision_feedback": "Do not imply a repair.", "layer": "llm",
    }


class FakeAPIError(Exception):
    code = 400


class ScriptedLLM:
    """Returns the scripted answers per schema name, in order; the last answer repeats."""

    def __init__(self, monkeypatch, analysis_=None, drafts=None, compliances=None):
        llm.reset_daily_counter()
        self.scripts = {
            "AnalysisResult": [analysis_ if analysis_ is not None else analysis()],
            "DraftResult": [draft(d) if isinstance(d, str) else d for d in (drafts or [CLEAN_SIMPLE])],
            "ComplianceResult": compliances or [compliance(True)],
        }
        self.counts = {k: 0 for k in self.scripts}
        self.prompts = []
        monkeypatch.setattr(llm, "_call_gemini", self)

    def __call__(self, prompt, system, schema):
        name = schema.__name__
        self.prompts.append((name, prompt))
        seq = self.scripts[name]
        item = seq[min(self.counts[name], len(seq) - 1)]
        self.counts[name] += 1
        if isinstance(item, Exception):
            raise item
        return item if isinstance(item, str) else json.dumps(item)

    @property
    def total(self):
        return sum(self.counts.values())
