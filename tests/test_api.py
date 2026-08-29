from fastapi.testclient import TestClient

from tokenledger.api import app

client = TestClient(app)


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


def test_quadrant_endpoint():
    r = client.get("/quadrant", params={
        "lob_id": "insurance", "tool_id": "claims_triage_agent", "week_from": 1, "week_to": 6})
    assert r.status_code == 200
    assert r.json()["quadrant"] == "Growing + Wasteful"


def test_quadrant_requires_a_dimension():
    assert client.get("/quadrant", params={"week_from": 1, "week_to": 6}).status_code == 422
