"""Discord alerts (Phase 5). Sends one embed per important ticket.

Rule: an alert problem must never block saving a ticket. Every function here
catches its own errors, logs a short message (never the webhook URL) and returns False.
"""
import logging
from datetime import datetime, timezone

import httpx

from app.config import settings

logger = logging.getLogger("intentgrid.discord")

COLOR_HIGH = 0xE74C3C    # red
COLOR_MEDIUM = 0xF39C12  # orange
COLOR_LOW = 0x2ECC71     # green
TIMEOUT_SECONDS = 10


def priority_level(ticket) -> str:
    """high / medium / low, from urgency and loss risk."""
    urgency = getattr(ticket, "urgency_score", None) or 0
    loss = (getattr(ticket, "loss_risk", None) or "").lower()
    if urgency >= 4 or loss == "high":
        return "high"
    if urgency == 3 or loss == "medium":
        return "medium"
    return "low"


def _cut(text, limit: int) -> str:
    text = str(text) if text not in (None, "") else "-"
    return text if len(text) <= limit else text[: limit - 3] + "..."


def dashboard_link(ticket_id) -> str | None:
    base = getattr(settings, "dashboard_url", "").rstrip("/")
    return f"{base}/tickets/{ticket_id}" if base else None


def build_embed(ticket, reason: str | None = None) -> dict:
    """Builds the Discord embed (a dict). Works with a Ticket row or any object with the same fields."""
    level = priority_level(ticket)
    color = {"high": COLOR_HIGH, "medium": COLOR_MEDIUM, "low": COLOR_LOW}[level]
    urgency = getattr(ticket, "urgency_score", None)
    fields = [
        {"name": "Category", "value": _cut(getattr(ticket, "category", None), 100), "inline": True},
        {"name": "Urgency", "value": f"{urgency}/5" if urgency is not None else "-", "inline": True},
        {"name": "Sentiment", "value": _cut(getattr(ticket, "sentiment", None), 100), "inline": True},
        {"name": "Loss risk", "value": _cut(getattr(ticket, "loss_risk", None), 100), "inline": True},
        {"name": "Status", "value": _cut(getattr(ticket, "status", None), 100), "inline": True},
    ]
    if reason:
        fields.append({"name": "Why this alert", "value": _cut(reason, 1000), "inline": False})
    link = dashboard_link(ticket.id)
    if link:
        fields.append({"name": "Dashboard", "value": f"[Open ticket #{ticket.id}]({link})", "inline": False})
    embed = {
        "title": _cut(f"Ticket #{ticket.id}: {getattr(ticket, 'subject', '')}", 256),
        "description": _cut(getattr(ticket, "summary", None), 1500),
        "color": color,
        "fields": fields,
        "footer": {"text": f"IntentGrid | {level.upper()} priority"},
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    if link:
        embed["url"] = link
    return embed


def send_embed(embed: dict, webhook_url: str | None = None, transport: httpx.BaseTransport | None = None) -> bool:
    """Posts one embed. Returns True on success. Never raises."""
    url = webhook_url if webhook_url is not None else settings.discord_webhook_url
    if not url:
        logger.warning("Discord webhook is not set; alert skipped")
        return False
    try:
        with httpx.Client(timeout=TIMEOUT_SECONDS, transport=transport) as client:
            response = client.post(url, json={"username": "IntentGrid", "embeds": [embed]})
        if response.status_code in (200, 204):
            return True
        logger.warning("Discord returned status %s; alert not sent", response.status_code)
    except Exception as exc:  # network error, bad URL, timeout...
        logger.warning("Discord alert failed: %s", type(exc).__name__)
    return False


def send_ticket_alert(ticket, reason: str | None = None, webhook_url: str | None = None,
                      transport: httpx.BaseTransport | None = None) -> bool:
    """Build and send the alert for one ticket. Never raises."""
    try:
        return send_embed(build_embed(ticket, reason), webhook_url, transport)
    except Exception as exc:
        logger.warning("Could not build Discord alert: %s", type(exc).__name__)
        return False


# ---- Step 5.2: trigger rules ----

def alert_reason(ticket) -> str | None:
    """Why this ticket deserves an alert, or None. Rules: urgency 4+, high loss risk,
    needs_manual_reply, send_failed. Spam is never alerted."""
    if getattr(ticket, "is_spam", False):
        return None
    reasons = []
    urgency = getattr(ticket, "urgency_score", None)
    if urgency is not None and urgency >= 4:
        reasons.append(f"Urgency {urgency}/5")
    if (getattr(ticket, "loss_risk", None) or "").lower() == "high":
        reasons.append("High loss risk")
    status = getattr(ticket, "status", None)
    if status == "needs_manual_reply":
        reasons.append("Needs a manual reply")
    if status == "send_failed":
        reasons.append("Email sending failed")
    return ", ".join(reasons) or None


def maybe_alert(db, ticket_id: int, business_id: int = 1) -> bool:
    """Loads the saved ticket and alerts if a rule matches. Never raises, never blocks saving."""
    try:
        from repositories import tickets as ticket_repo

        ticket = ticket_repo.get_ticket(db, ticket_id, business_id)
        if ticket is None:
            return False
        reason = alert_reason(ticket)
        return send_ticket_alert(ticket, reason) if reason else False
    except Exception as exc:
        logger.warning("Alert check failed for ticket %s: %s", ticket_id, type(exc).__name__)
        return False
