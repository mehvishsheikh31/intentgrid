from fastapi.testclient import TestClient  # noqa: F401
from unittest.mock import patch

from app.config import settings
from integrations import discord as d
from repositories.tickets import get_ticket
from test_trigger import make_ticket


def test_maybe_alert_sends_for_high_risk(db):
    t = make_ticket(db, status="needs_manual_reply")
    with patch.object(d, "send_ticket_alert", return_value=True) as sent:
        assert d.maybe_alert(db, t.id) is True
    assert sent.call_args.args[1] == "Needs a manual reply"


def test_maybe_alert_quiet_for_normal_ticket(db):
    t = make_ticket(db, status="awaiting_approval")
    with patch.object(d, "send_ticket_alert") as sent:
        assert d.maybe_alert(db, t.id) is False
    sent.assert_not_called()


def test_wrong_webhook_never_blocks_saving(db, monkeypatch):
    t = make_ticket(db, status="needs_manual_reply")
    monkeypatch.setattr(settings, "discord_webhook_url", "http://127.0.0.1:9/bad")
    assert d.maybe_alert(db, t.id) is False
    assert get_ticket(db, t.id).status == "needs_manual_reply"


def test_discord_test_endpoint_needs_webhook(client):
    r = client.post("/api/discord/test")
    assert r.status_code == 400
