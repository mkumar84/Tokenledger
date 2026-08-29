from fastapi.testclient import TestClient

from tokenledger.api import app

client = TestClient(app)


def test_cors_allowlisted_origin_gets_headers():
    r = client.get("/health", headers={"Origin": "http://localhost:5173"})
    assert r.headers.get("access-control-allow-origin") == "http://localhost:5173"


def test_cors_unknown_origin_not_reflected():
    r = client.get("/health", headers={"Origin": "https://evil.example.com"})
    assert r.headers.get("access-control-allow-origin") != "https://evil.example.com"


def test_cors_origins_come_from_env(monkeypatch):
    monkeypatch.setenv("TOKENLEDGER_CORS_ORIGINS", "https://foo.lovable.app, https://bar.app")
    from tokenledger import config

    assert config.cors_origins() == ["https://foo.lovable.app", "https://bar.app"]


def test_health():
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["sessions_loaded"] > 4000


def test_cost_endpoint():
    r = client.get("/cost", params={"group_by": "lob_tool", "week_from": 1, "week_to": 4})
    assert r.status_code == 200
    assert r.json()["slices"]


def test_cost_drivers_endpoint():
    r = client.get("/cost/drivers", params={
        "group_by": "lob", "a_from": 1, "a_to": 3, "b_from": 10, "b_to": 12})
    assert r.status_code == 200
    for sl in r.json()["slices"]:
        assert abs(sl["residual_usd"]) < 1e-5


def test_adoption_endpoint():
    r = client.get("/adoption", params={"group_by": "tool"})
    assert r.status_code == 200


def test_anti_patterns_endpoint_rejects_lob_tool():
    assert client.get("/anti-patterns", params={"group_by": "lob_tool"}).status_code == 422
    assert client.get("/anti-patterns", params={"group_by": "tool"}).status_code == 200


def test_recommendations_endpoint():
    r = client.get("/recommendations")
    assert r.status_code == 200
    assert r.json()["recommendations"]


def test_quadrant_single_slice_flat_shape_unchanged():
    r = client.get("/quadrant", params={
        "lob_id": "insurance", "tool_id": "claims_triage_agent", "week_from": 1, "week_to": 6})
    assert r.status_code == 200
    body = r.json()
    assert "results" not in body            # flat, not batch
    assert body["quadrant"] == "Growing + Wasteful"


def test_quadrant_bare_is_batch_all():
    r = client.get("/quadrant", params={"week_from": 1, "week_to": 12})
    assert r.status_code == 200
    body = r.json()
    results = body["results"]
    assert body["count"] == len(results)
    # every LOB (tool_id null) and every tool (lob_id null) present, plus cells
    assert {x["lob_id"] for x in results if x["tool_id"] is None} == {
        "insurance", "retail_banking", "wealth_management", "commercial_lending"}
    assert {x["tool_id"] for x in results if x["lob_id"] is None} >= {"cursor", "claude_code"}
    assert any(x["lob_id"] and x["tool_id"] for x in results)


def test_quadrant_explicit_batch_lists():
    r = client.get("/quadrant", params={
        "lob_ids": "insurance,retail_banking", "week_from": 1, "week_to": 12})
    got = {x["lob_id"] for x in r.json()["results"]}
    assert got == {"insurance", "retail_banking"}

    r2 = client.get("/quadrant", params={
        "lob_ids": "insurance", "tool_ids": "cursor,claude_code", "week_from": 1, "week_to": 12})
    cells = {(x["lob_id"], x["tool_id"]) for x in r2.json()["results"]}
    assert cells == {("insurance", "cursor"), ("insurance", "claude_code")}


def test_quadrant_requires_weeks():
    assert client.get("/quadrant").status_code == 422


def test_quadrant_layer_scopes_to_managed_agent():
    r = client.get("/quadrant", params={
        "layer": "L1_managed_agent", "week_from": 1, "week_to": 12})
    assert r.status_code == 200
    cells = {(x["lob_id"], x["tool_id"]): x["quadrant"]
             for x in r.json()["results"] if x["lob_id"] and x["tool_id"]}
    assert cells[("retail_banking", "aml_alert_triage")] == "Stalled + Wasteful"
    assert cells[("insurance", "claims_triage_agent")] == "Growing + Efficient"
    # the un-scoped whole-LOB row disagrees — that was the bug
    whole = client.get("/quadrant", params={
        "lob_id": "retail_banking", "week_from": 1, "week_to": 12}).json()
    assert whole["quadrant"] != "Stalled + Wasteful"


def test_quadrant_bad_layer_rejected():
    assert client.get("/quadrant", params={
        "layer": "L9_bogus", "week_from": 1, "week_to": 12}).status_code == 422


def test_health_exposes_agent_taxonomy():
    h = client.get("/health").json()
    assert h["lob_managed_agents"]["retail_banking"] == ["aml_alert_triage"]
    assert h["tool_categories"]["aml_alert_triage"] == "managed_agent"
    assert h["tool_categories"]["cursor"] == "interactive_dev_harness"
