import os
import sys
from pathlib import Path

import httpx
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

url = os.getenv("DISCORD_WEBHOOK_URL")
if not url:
    sys.exit("DISCORD_WEBHOOK_URL is missing in backend/.env")

r = httpx.post(url, json={"content": "IntentGrid test message: Discord works."}, timeout=15)
print("Status:", r.status_code)
if r.status_code not in (200, 204):
    sys.exit(f"Failed: {r.text}")
print("Message sent. Check your #alerts channel.")
