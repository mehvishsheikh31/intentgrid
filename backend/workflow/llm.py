import re
import time
from datetime import datetime, timezone
from typing import TypeVar

from pydantic import BaseModel, ValidationError

from app.config import settings

T = TypeVar("T", bound=BaseModel)

MAX_RETRIES = 3  # retries after the first try, for 429 and 5xx errors
BASE_DELAY = 1.0  # seconds; doubles each retry: 1, 2, 4


class LLMError(Exception):
    """Any LLM failure the workflow should treat as workflow_failed."""


# ---- daily counter (in memory; resets at UTC midnight or on restart) ----
_daily = {"date": None, "count": 0}


def _today() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def _bump_daily() -> None:
    today = _today()
    if _daily["date"] != today:
        _daily["date"] = today
        _daily["count"] = 0
    _daily["count"] += 1


def get_daily_count() -> int:
    return _daily["count"] if _daily["date"] == _today() else 0


def reset_daily_counter() -> None:
    _daily["date"] = None
    _daily["count"] = 0


# ---- the only place that talks to Gemini ----
_client = None


def _get_client():
    global _client
    if _client is None:
        if not settings.gemini_api_key:
            raise LLMError("GEMINI_API_KEY is missing in backend/.env")
        from google import genai

        _client = genai.Client(api_key=settings.gemini_api_key)
    return _client


def _call_gemini(prompt: str, system: str | None, schema: type[BaseModel]) -> str:
    from google.genai import types

    config = types.GenerateContentConfig(
        system_instruction=system,
        response_mime_type="application/json",
        response_schema=schema,
        temperature=0.2,
    )
    response = _get_client().models.generate_content(
        model=settings.gemini_model, contents=prompt, config=config
    )
    return response.text or ""


def _sleep(seconds: float) -> None:
    time.sleep(seconds)


def _is_retryable(exc: Exception) -> bool:
    code = getattr(exc, "code", None)
    return isinstance(code, int) and (code == 429 or code >= 500)


def _request(prompt: str, system: str | None, schema: type[BaseModel]) -> str:
    """One logical request with exponential backoff on 429 and 5xx."""
    for attempt in range(MAX_RETRIES + 1):
        _bump_daily()  # every real request counts against the daily quota
        try:
            return _call_gemini(prompt, system, schema)
        except Exception as exc:
            if not _is_retryable(exc):
                raise LLMError(f"LLM call failed: {exc}") from exc
            if attempt == MAX_RETRIES:
                raise LLMError(
                    f"LLM unavailable after {MAX_RETRIES} retries: {exc}"
                ) from exc
            _sleep(BASE_DELAY * 2**attempt)
    raise LLMError("unreachable")  # pragma: no cover


def _parse(text: str, schema: type[T]) -> T:
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip())
    return schema.model_validate_json(cleaned)  # raises ValidationError


def generate_structured(
    prompt: str,
    schema: type[T],
    *,
    system: str | None = None,
    state: dict | None = None,
) -> T:
    """Call Gemini, return a validated object.

    - adds 1 to state["llm_calls"] per request made (a repair retry adds 1 more)
    - 429 and 5xx: exponential backoff
    - invalid JSON: one repair retry, then LLMError
    """

    def count() -> None:
        if state is not None:
            state["llm_calls"] = state.get("llm_calls", 0) + 1

    text = _request(prompt, system, schema)
    count()
    try:
        return _parse(text, schema)
    except ValidationError as err:
        problem = str(err)[:500]
        repair_prompt = (
            f"{prompt}\n\nYour previous answer was not valid.\n"
            f"Problem: {problem}\n"
            "Return ONLY valid JSON that matches the schema. No other text."
        )
        text = _request(repair_prompt, system, schema)
        count()
        try:
            return _parse(text, schema)
        except ValidationError as err2:
            raise LLMError("Model returned invalid JSON twice") from err2