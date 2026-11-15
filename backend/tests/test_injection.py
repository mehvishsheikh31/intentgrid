"""Step 4.10: prompt-injection safeguards. All offline (fake Gemini), no quota used.

The fake model here is OBEDIENT: it does whatever the malicious message asks. The tests prove
the code around the model (delimiters, rules, schema checks, boosters) still holds.
"""
import json
from pathlib import Path

import pytest

from agents.compliance_rules import blockers, check_rules
from app.schemas import ContactSubmission
from llm_fakes import CLEAN_RISKY, ScriptedLLM, analysis
from repositories.policies import upsert_policy
from repositories.tickets import create_ticket, get_ticket
from scripts_loader import load_sample_policy
from workflow.router import is_obvious_spam
from workflow.runner import process_ticket

DATA = Path(__file__).resolve().parents[1] / "data" / "injection_messages.json"
CASES = json.loads(DATA.read_text(encoding="utf-8"))
DRAFT_CASES = [c for c in CASES if c["obedient_draft"]]
POLICY = load_sample_policy().policy_text


def make_ticket(db, case):
    upsert_policy(db, load_sample_policy())
    return create_ticket(
        db,
        ContactSubmission(
            name="Asha Verma", email="asha@example.com", category=case["category"],
            subject=case["subject"], message=case["message"],
        ),
    )


def test_there_are_eight_valid_cases():
    assert len(CASES) == 8
    assert len({c["id"] for c in CASES}) == 8
    for c in CASES:
        assert {"id", "label", "category", "subject", "message", "expected_rule", "forbidden"} <= set(c)
    assert len(DRAFT_CASES) == 7


@pytest.mark.parametrize("case", CASES, ids=lambda c: c["id"])
def test_injection_messages_are_not_hidden_by_the_spam_precheck(case):
    # They must go through the real agents, so the other safeguards are the ones being tested.
    assert is_obvious_spam(case["subject"], case["message"]) is False


@pytest.mark.parametrize("case", CASES, ids=lambda c: c["id"])
def test_customer_text_stays_inside_one_delimiter_pair_in_every_prompt(db, monkeypatch, case):
    fake = ScriptedLLM(
        monkeypatch, analysis_=analysis(category="complaint", loss="high"), drafts=[CLEAN_RISKY]
    )
    ticket = make_ticket(db, case)
    process_ticket(db, ticket.id)
    seen = {name for name, _ in fake.prompts}
    assert seen == {"AnalysisResult", "DraftResult", "ComplianceResult"}  # all three prompts checked
    for name, prompt in fake.prompts:
        assert prompt.count("<customer_message>") == 1, name
        assert prompt.count("</customer_message>") == 1, name
        assert prompt.index("<customer_message>") < prompt.index("</customer_message>"), name


@pytest.mark.parametrize("case", DRAFT_CASES, ids=lambda c: c["id"])
def test_an_obedient_model_can_never_get_a_forbidden_draft_approved(db, monkeypatch, case):
    fake = ScriptedLLM(monkeypatch, drafts=[case["obedient_draft"]])  # the model does what it is told
    ticket = make_ticket(db, case)
    outcome = process_ticket(db, ticket.id)
    t = get_ticket(db, ticket.id)
    assert outcome.status == "needs_manual_reply"  # never awaiting_approval
    assert outcome.revision_count == 2
    assert t.compliance_status == "failed"
    assert case["expected_rule"] in {v["rule"] for v in t.compliance_violations}
    assert fake.counts["DraftResult"] == 3  # first draft + exactly 2 revisions


def test_an_injected_demand_for_low_risk_is_overridden_by_the_rules(db, monkeypatch):
    case = next(c for c in CASES if c["id"] == "force_low_risk")
    ScriptedLLM(
        monkeypatch, analysis_=analysis(category="other", urgency=1, loss="low"), drafts=[CLEAN_RISKY]
    )
    ticket = make_ticket(db, case)
    process_ticket(db, ticket.id)
    t = get_ticket(db, ticket.id)
    assert t.urgency_score == 5 and t.loss_risk == "high"
    assert any("Legal threat" in r for r in t.risk_reasons)


@pytest.mark.parametrize("stage", ["AnalysisResult", "DraftResult"])
def test_a_model_that_breaks_the_output_format_ends_safely(db, monkeypatch, stage):
    fake = ScriptedLLM(monkeypatch)
    # Raw text that is not JSON, exactly as an injected "print your system prompt" might produce.
    fake.scripts[stage] = ["Sure! Here is my system prompt: you are a helpful assistant."]
    ticket = make_ticket(db, CASES[1])
    outcome = process_ticket(db, ticket.id)
    t = get_ticket(db, ticket.id)
    assert outcome.status == "workflow_failed" and "invalid" in outcome.error.lower()
    assert t.status == "workflow_failed" and t.draft_reply is None
    assert fake.counts[stage] == 2  # the first answer plus exactly one repair retry


# ---------- the rules added in 4.10 ----------

def rules_for(text, **kw):
    return {v.rule for v in blockers(check_rules(text, POLICY, **kw))}


def test_policy_email_and_customers_own_email_are_allowed():
    assert rules_for("Write to support@technest.example") == set()
    assert rules_for("We will write to rahul@example.com", allowed_emails=["rahul@example.com"]) == set()


def test_other_emails_and_phone_numbers_are_blocked():
    assert "unapproved_contact" in rules_for("Mail attacker@evil.com")
    assert "unapproved_contact" in rules_for("Call 9876543210 now")
    assert rules_for("We will call you on +91 98765 43210", allowed_phones=["9876543210"]) == set()
    assert rules_for("Your ORD-20261104-77 has shipped") == set()  # an order number is not a phone


def test_secrets_are_blocked_but_a_safety_tip_is_not():
    assert "secret_sharing" in rules_for("The password: hunter2")
    assert rules_for("Please never share your password with anyone") == set()


def test_free_replacement_promises_are_blocked_but_updates_are_not():
    assert "refund_commitment" in rules_for("you will get a free replacement")
    assert "refund_commitment" in rules_for("we can give you two free replacements")
    assert rules_for("We will give you an update on the replacement.") == set()
