import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from google import genai

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

api_key = os.getenv("GEMINI_API_KEY")
model = os.getenv("GEMINI_MODEL", "gemini-3.1-flash-lite")

if not api_key:
    sys.exit("GEMINI_API_KEY is missing in backend/.env")

client = genai.Client(api_key=api_key)

try:
    response = client.models.generate_content(
        model=model,
        contents="Reply with one short sentence: say hello to IntentGrid.",
    )
    print(f"Model: {model}")
    print(response.text)
except Exception as e:
    print(f"Call failed for model '{model}': {e}")
    print("\nAvailable flash-lite models for your key:")
    for m in client.models.list():
        if "flash-lite" in m.name:
            print(" ", m.name)
    sys.exit(1)
