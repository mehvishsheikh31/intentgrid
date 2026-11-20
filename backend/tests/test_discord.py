import json
from types import SimpleNamespace

import httpx

from integrations import discord as d


def ticket(**kw):
    base = dict(id=7, subject="Refund please", category="complaint", urgency_score=5, sentiment="angry",
                loss_risk="high", status="awaiting_approval", summary="Wants a refund.")
    base.update(kw)
    return SimpleNamespace(**base)


def test_colour_by_priority():
    assert d.build_embed(ticket())["color"] == d.COLOR_HIGH
    assert d.build_embed(ticket(urgency_score=3, loss_risk="low"))["color"] == d.COLOR_MEDIUM
    assert d.build_embed(ticket(urgency_score=1, loss_risk="low"))["color"] == d.COLOR_LOW
    assert d.build_embed(ticket(urgency_score=1, loss_risk="high"))["color"] == d.COLOR_HIGH


def test_embed_has_required_fields_and_limits():
    embed = d.build_embed(ticket(subject="x" * 500, summary="y" * 5000), reason="High urgency")
    names = {f["name"] for f in embed["fields"]}
    assert {"Category", "Urgency", "Sentiment", "Loss risk", "Why this alert"} <= names
    assert len(embed["title"]) <= 256 and len(embed["description"]) <= 4096
    assert embed["title"].startswith("Ticket #7")


def test_dashboard_link_added_when_configured(monkeypatch):
    monkeypatch.setattr(d.settings, "dashboard_url", "https://dash.example.com/", raising=False)
    embed = d.build_embed(ticket())
    assert embed["url"] == "https://dash.example.com/tickets/7"
    assert any(f["name"] == "Dashboard" for f in embed["fields"])


def test_send_posts_embed():
    seen = {}

    def handler(request):
        seen["body"] = json.loads(request.content)
        return httpx.Response(204)

    assert d.send_ticket_alert(ticket(), webhook_url="https://x.test/hook", transport=httpx.MockTransport(handler))
    assert seen["body"]["embeds"][0]["title"].startswith("Ticket #7")


def test_failures_never_raise():
    boom = httpx.MockTransport(lambda r: (_ for _ in ()).throw(httpx.ConnectError("down")))
    assert d.send_ticket_alert(ticket(), webhook_url="https://x.test/hook", transport=boom) is False
    bad = httpx.MockTransport(lambda r: httpx.Response(404))
    assert d.send_ticket_alert(ticket(), webhook_url="https://x.test/hook", transport=bad) is False
    assert d.send_ticket_alert(ticket(), webhook_url="") is False
    assert d.send_ticket_alert(object(), webhook_url="https://x.test/hook") is False


# ---- Step 5.2 ----
def test_alert_reason_rules():
    assert d.alert_reason(ticket()) == "Urgency 5/5, High loss risk"
    assert d.alert_reason(ticket(urgency_score=2, loss_risk="low", status="needs_manual_reply"))
    assert d.alert_reason(ticket(urgency_score=2, loss_risk="low", status="send_failed"))
    assert d.alert_reason(ticket(urgency_score=3, loss_risk="medium")) is None
    assert d.alert_reason(ticket(is_spam=True)) is None
