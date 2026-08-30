"""'Ask TokenLedger' grounded chat (Backend Patch 7).

Plumbing tests (context assembly, grounding-data contents, rate limiting,
validation, unconfigured 503) run always. The two tests that make a real Claude
API call are skipped unless ANTHROPIC_API_KEY is set."""
import json
import os

import pytest
from fastapi.testclient import TestClient

from tokenledger import api
from tokenledger.chat import build_context
from tokenledger.ratelimit import SlidingWindowLimiter

client = TestClient(api.app)
LIVE = bool(os.environ.get("ANTHROPIC_API_KEY"))
needs_key = pytest.mark.skipif(not LIVE, reason="ANTHROPIC_API_KEY not set")


@pytest.fixture(autouse=True)
def _reset_limiter():
    api.CHAT_LIMITER.reset()
    yield
    api.CHAT_LIMITER.reset()


# --- rate limiter unit ------------------------------------------------

def test_sliding_window_limiter():
    lim = SlidingWindowLimiter(max_requests=3, window_seconds=100)
    assert [lim.check("ip", now=t) for t in (0, 1, 2)] == [True, True, True]
    assert lim.check("ip", now=3) is False           # 4th within window -> blocked
    assert lim.check("other", now=3) is True          # keyed per client
    assert lim.retry_after_seconds("ip", now=3) >= 1  # at limit -> non-zero wait
    assert lim.check("ip", now=201) is True            # all three hits aged out
    assert lim.retry_after_seconds("ip", now=201) == 0


# --- context bundle: grounded, not generative -----------------------

def test_bundle_has_no_raw_session_data():
    bundle, _ = build_context(1, 12)
    blob = json.dumps(bundle)
    for forbidden in ("session_id", "user_id", "turn_count", "tokens_in", "cost_usd"):
        assert forbidden not in blob, f"{forbidden} leaked into the chat context bundle"


def test_bundle_contains_planted_arc_facts():
    bundle, _ = build_context(1, 12)
    blob = json.dumps(bundle)
    # the same facts the dashboards show
    assert '"aml_alert_triage"' in blob and "Stalled + Wasteful" in blob
    assert "credit_memo_agent" in blob and "Stalled + Efficient" in blob
    assert "saas_mcp_assist" in blob and "consolidate" in blob
    assert "consumption_spend_usd" in blob and "license_spend_usd" in blob
    # quadrant_lob_agent row for retail_banking / aml is present and correct
    q = bundle["quadrant_lob_agent"]["results"]
    cell = next(r for r in q if r["lob_id"] == "retail_banking" and r["tool_id"] == "aml_alert_triage")
    assert cell["quadrant"] == "Stalled + Wasteful"


def test_grounded_in_names_every_source():
    _, grounded = build_context(1, 12)
    assert set(grounded) == {
        "cost:lob", "adoption:lob", "adoption:tool",
        "quadrant:layer=L1_managed_agent", "quadrant:tool",
        "recommendations", "anti-patterns:tool",
    }


def test_bundle_stays_reasonably_small():
    bundle, _ = build_context(1, 12)
    assert len(json.dumps(bundle)) < 90_000  # ~a handful of KB, not raw rows


# --- endpoint plumbing ---------------------------------------------

def test_chat_503_when_unconfigured(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    r = client.post("/chat", json={"question": "which LOB has the most usage?"})
    assert r.status_code == 503
    assert "not configured" in r.json()["detail"].lower()


def test_chat_validation_rejects_empty_and_overlong(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    assert client.post("/chat", json={"question": ""}).status_code == 422
    assert client.post("/chat", json={"question": "x" * 5000}).status_code == 422
    assert client.post("/chat", json={
        "question": "ok", "conversation_history": [{"role": "bogus", "content": "x"}]
    }).status_code == 422


def test_chat_rate_limit_returns_429(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setattr(
        api, "answer_question",
        lambda *a, **k: {"answer": "stub", "grounded_in": []},
    )
    ok = [client.post("/chat", json={"question": "hi"}).status_code for _ in range(20)]
    assert ok == [200] * 20
    blocked = client.post("/chat", json={"question": "hi"})
    assert blocked.status_code == 429
    assert "try again" in blocked.json()["detail"].lower()
    assert int(blocked.headers.get("retry-after", "0")) >= 1


def test_chat_happy_path_shape(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    captured = {}

    def fake_answer(question, wf, wt, history, **kw):
        captured["args"] = (question, wf, wt, list(history))
        return {"answer": "Retail Banking, per quadrant_lob_agent.", "grounded_in": ["quadrant:layer=L1_managed_agent"]}

    monkeypatch.setattr(api, "answer_question", fake_answer)
    r = client.post("/chat", json={
        "question": "which LOB is stalled and wasteful?",
        "week_from": 3, "week_to": 9,
        "conversation_history": [{"role": "user", "content": "hi"}, {"role": "assistant", "content": "hello"}],
    })
    assert r.status_code == 200
    body = r.json()
    assert set(body) == {"answer", "grounded_in"}
    assert captured["args"][0] == "which LOB is stalled and wasteful?"
    assert captured["args"][1:3] == (3, 9)
    assert len(captured["args"][3]) == 2


# --- live grounding / refusal (real API call) --------------------

@needs_key
@pytest.mark.parametrize("question,must_include", [
    ("Which LOB is stalled and wasteful?", ["retail"]),
    ("Which tool is flagged for licence consolidation?", ["saas"]),
    ("Which LOB's managed agent is the healthy reference implementation?", ["wealth"]),
])
def test_chat_grounding_live(question, must_include):
    r = client.post("/chat", json={"question": question, "week_from": 1, "week_to": 12})
    assert r.status_code == 200
    answer = r.json()["answer"].lower()
    for token in must_include:
        assert token in answer, f"expected {token!r} in: {answer}"


@needs_key
def test_chat_refuses_out_of_scope_forecast_live():
    r = client.post("/chat", json={
        "question": "What will total spend be next year?",
        "week_from": 1, "week_to": 12,
    })
    assert r.status_code == 200
    answer = r.json()["answer"].lower()
    assert any(p in answer for p in (
        "can't", "cannot", "unable", "not able", "no forecast", "don't have",
        "do not have", "not available", "outside", "isn't", "is not", "no data",
    )), f"expected a refusal, got: {answer}"
