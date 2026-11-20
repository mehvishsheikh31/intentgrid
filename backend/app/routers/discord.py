from types import SimpleNamespace

from fastapi import APIRouter, HTTPException

from app.config import settings
from integrations.discord import send_ticket_alert

router = APIRouter(prefix="/api/discord", tags=["discord"])


@router.post("/test")
def discord_test():
    """Sends a sample alert so the owner can check the webhook (used by the dashboard in Phase 6)."""
    if not settings.discord_webhook_url:
        raise HTTPException(status_code=400, detail="Discord webhook is not set.")
    sample = SimpleNamespace(
        id=0, subject="Test alert from IntentGrid", category="test", urgency_score=4, sentiment="neutral",
        loss_risk="low", status="test", summary="If you can see this, Discord alerts are working.",
    )
    if not send_ticket_alert(sample, reason="Test alert"):
        raise HTTPException(status_code=502, detail="Discord did not accept the alert. Check the webhook URL.")
    return {"sent": True}
