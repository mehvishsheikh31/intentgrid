import pytest
from pydantic import BaseModel

from workflow import llm


class Demo(BaseModel):
    answer: str


class FakeAPIError(Exception):
    def __init__(self, code: int):
        super().__init__(f"error {code}")
        self.code = code


@pytest.fixture(autouse=True)
def sleeps(monkeypatch):
    llm.reset_daily_counter()
    recorded = []
    monkeypatch.setattr(llm, "_sleep", lambda s: recorded.append(s))
    return recorded


def script(monkeypatch, outputs):
    calls = []

    def fake(prompt, system, schema):
        calls.append(prompt)
        item = outputs[len(calls) - 1]
        if isinstance(item, Exception):
            raise item
        return item

    monkeypatch.setattr(llm, "_call_gemini", fake)
    return calls


def test_success_counts_one_call(monkeypatch):
    script(monkeypatch, ['{"answer": "hi"}'])
    state = {"llm_calls": 0}
    result = llm.generate_structured("p", Demo, state=state)
    assert result == Demo(answer="hi")
    assert state["llm_calls"] == 1
    assert llm.get_daily_count() == 1


def test_works_without_state(monkeypatch):
    script(monkeypatch, ['{"answer": "hi"}'])
    assert llm.generate_structured("p", Demo).answer == "hi"


def test_code_fence_is_stripped(monkeypatch):
    script(monkeypatch, ['```json\n{"answer": "hi"}\n```'])
    assert llm.generate_structured("p", Demo).answer == "hi"


def test_repair_retry_after_invalid_json(monkeypatch):
    calls = script(monkeypatch, ["not json", '{"answer": "ok"}'])
    state = {"llm_calls": 0}
    result = llm.generate_structured("p", Demo, state=state)
    assert result.answer == "ok"
    assert state["llm_calls"] == 2
    assert "not valid" in calls[1]


def test_invalid_twice_raises(monkeypatch):
    calls = script(monkeypatch, ["bad", "still bad"])
    with pytest.raises(llm.LLMError):
        llm.generate_structured("p", Demo)
    assert len(calls) == 2


def test_backoff_on_429(monkeypatch, sleeps):
    script(monkeypatch, [FakeAPIError(429), '{"answer": "ok"}'])
    state = {"llm_calls": 0}
    result = llm.generate_structured("p", Demo, state=state)
    assert result.answer == "ok"
    assert sleeps == [1.0]
    assert state["llm_calls"] == 1
    assert llm.get_daily_count() == 2  # both real requests count for quota


def test_retries_exhausted(monkeypatch, sleeps):
    calls = script(monkeypatch, [FakeAPIError(503)] * 4)
    with pytest.raises(llm.LLMError):
        llm.generate_structured("p", Demo)
    assert sleeps == [1.0, 2.0, 4.0]
    assert len(calls) == 4


def test_non_retryable_error_fails_fast(monkeypatch, sleeps):
    calls = script(monkeypatch, [FakeAPIError(400)])
    with pytest.raises(llm.LLMError):
        llm.generate_structured("p", Demo)
    assert len(calls) == 1
    assert sleeps == []