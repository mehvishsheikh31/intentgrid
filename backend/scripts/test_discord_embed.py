"""Step 5.1: post a sample ticket embed to your Discord #alerts channel.

Run from the backend folder:
  python scripts\\test_discord_embed.py            high-priority sample (red)
  python scripts\\test_discord_embed.py medium     orange sample
  python scripts\\test_discord_embed.py low         green sample
"""
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from app.config import settings  # noqa: E402
from integrations.discord import send_ticket_alert  # noqa: E402

SAMPLES = {
    "high": dict(id=901, subject="Laptop died after 2 days, want refund now", category="complaint",
                 urgency_score=5, sentiment="angry", loss_risk="high", status="awaiting_approval",
                 summary="Customer says the laptop stopped working after two days and demands a refund or will go to consumer court."),
    "medium": dict(id=902, subject="Delivery is late", category="order_status",
                   urgency_score=3, sentiment="negative", loss_risk="medium", status="awaiting_approval",
                   summary="Customer asks where a delayed order is."),
    "low": dict(id=903, subject="Do you sell USB cables?", category="product_inquiry",
                urgency_score=1, sentiment="neutral", loss_risk="low", status="awaiting_approval",
                summary="Customer asks if USB-C cables are in stock."),
}

level = sys.argv[1] if len(sys.argv) > 1 else "high"
if level not in SAMPLES:
    sys.exit("Use: high, medium or low")
if not settings.discord_webhook_url:
    sys.exit("DISCORD_WEBHOOK_URL is missing in backend/.env")

ok = send_ticket_alert(SimpleNamespace(**SAMPLES[level]), reason="Test alert from step 5.1")
print("Embed sent. Check your #alerts channel." if ok else "FAILED. Check the webhook URL and the log above.")
sys.exit(0 if ok else 1)
