import pytest

from workflow import router
from workflow.schemas import ComplianceResult, RiskResult, UnderstandingResult

SPAM_PRIZE = (
    "CONGRATULATIONS!!! You won 1,000,000 dollars. Click http://bit.ly/free-prize now "
    "to claim your free iPhone."
)


@pytest.mark.parametrize(
    "subject, message",
    [
        ("You won", SPAM_PRIZE),
        ("Links", "see http://a.com http://b.com http://c.com"),
        ("Money", "Earn money fast with crypto, work from home!"),
        ("Offer", "Visit www.cheap-pills.biz for your limited time offer"),
    ],
)
def test_obvious_spam_is_caught(subject, message):
    assert router.is_obvious_spam(subject, message) is True


@pytest.mark.parametrize(
    "subject, message",
    [
        ("Order", "Is the free shipping offer still valid on the AeroBook 14?"),
        ("Photo", "My SoundBud Air has no sound. Photo: https://imgur.com/abc123"),
        ("Crypto?", "Do you accept crypto payments for laptops?"),
        ("", ""),
        ("Angry", "You are scammers!!! I want my money back NOW!!!"),
    ],
)
def test_normal_messages_are_not_spam(subject, message):
    assert router.is_obvious_spam(subject, message) is False


def _state(category, loss):
    return {
        "understanding": UnderstandingResult(category=category, intent="x", summary="x", confidence=0.5),
        "risk": RiskResult(urgency_score=2, sentiment="neutral", loss_risk=loss),
    }


@pytest.mark.parametrize(
    "category, loss, expected",
    [
        ("product_inquiry", "low", "simple"),
        ("order_status", "low", "simple"),
        ("complaint", "low", "risky"),
        ("refund_request", "low", "risky"),
        ("feedback", "medium", "risky"),
        ("feedback", "high", "risky"),
    ],
)
def test_decide_route(category, loss, expected):
    assert router.decide_route(_state(category, loss)) == expected


def _compliance(passed):
    return ComplianceResult(passed=passed)


@pytest.mark.parametrize(
    "passed, revisions, expected",
    [(True, 0, "pass"), (True, 2, "pass"), (False, 0, "revise"), (False, 1, "revise"), (False, 2, "exhausted")],
)
def test_route_after_compliance(passed, revisions, expected):
    state = {"compliance": _compliance(passed), "revision_count": revisions, "max_revisions": 2}
    assert router.route_after_compliance(state) == expected


def test_precheck_and_understanding_routes():
    assert router.route_after_precheck({"route": "spam_precheck"}) == "spam"
    assert router.route_after_precheck({"route": None}) == "analyse"
    spam = UnderstandingResult(category="spam", intent="x", summary="x", is_spam=True, confidence=0.9)
    ham = UnderstandingResult(category="other", intent="x", summary="x", is_spam=False, confidence=0.9)
    assert router.route_after_understanding({"understanding": spam}) == "spam"
    assert router.route_after_understanding({"understanding": ham}) == "continue"
    assert router.route_after_understanding({}) == "continue"
