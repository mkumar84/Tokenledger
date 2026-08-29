"""Brief §4: iterate manifest.planted_arcs and assert each engine surfaces the
intended finding (directionally). If an arc doesn't surface, the engine logic
is wrong — the data is already validated (see data/validate.py)."""
import pytest

from tokenledger.engines.antipattern import detect
from tokenledger.engines.quadrant import classify
from tokenledger.engines.recommendation import recommend


# --- quadrant arcs ----------------------------------------------------

QUADRANT_ARCS = {
    "insurance_claims_triage_wasteful_to_efficient": [
        ("insurance", "claims_triage_agent", (1, 6), "Growing + Wasteful"),
        ("insurance", "claims_triage_agent", (9, 12), "Growing + Efficient"),
    ],
    "commercial_lending_credit_memo_stalled_efficient": [
        ("commercial_lending", "credit_memo_agent", (1, 12), "Stalled + Efficient"),
    ],
    "wealth_management_portfolio_summarizer_reference": [
        ("wealth_management", "portfolio_summarizer", (1, 12), "Growing + Efficient"),
    ],
    "retail_banking_aml_alert_triage_stalled_wasteful": [
        ("retail_banking", "aml_alert_triage", (1, 12), "Stalled + Wasteful"),
    ],
}


@pytest.mark.parametrize("arc_name", QUADRANT_ARCS)
def test_quadrant_arc(arc_name, arcs):
    assert arc_name in arcs
    for lob, tool, weeks, expected in QUADRANT_ARCS[arc_name]:
        got = classify(lob, tool, *weeks)["quadrant"]
        assert got == expected, f"{arc_name} {weeks}: got {got}, want {expected}"


# --- anti-pattern / governance arcs ---------------------------------

def test_arc_claude_code_cache_expiration_cross_lob(arcs):
    arc = arcs["claude_code_cache_expiration_cross_lob"]
    res = detect("tool", 1, 12)
    rollups = [
        f for f in res["tool_level_findings"]["claude_code"]
        if f.get("scope") == "tool_level_rollup" and f["category"] == "cache_expiration_churn"
    ]
    assert len(rollups) == 1
    assert sorted(rollups[0]["lobs"]) == sorted(arc["lobs"])


def test_arc_cursor_commercial_lending_legitimate_variance(arcs):
    arcs["cursor_commercial_lending_legitimate_variance"]
    res = detect("lob", 1, 12)
    flagged = [
        f for fs in res["lob_level_findings"].values() for f in fs
        if f["lob_id"] == "commercial_lending" and f["tool_id"] == "cursor"
        and f["category"] == "context_window_bloat"
    ]
    assert not flagged
    assert any(
        x["lob_id"] == "commercial_lending" and x["tool_id"] == "cursor"
        for x in res["legitimate_variance_exclusions"]
    )


@pytest.mark.parametrize("arc_name,tool_id,check", [
    ("saas_mcp_assist_underutilized_seats", "saas_mcp_assist",
     lambda r: r["source"] == "adoption.seat_utilization" and r["dollar_impact_usd"] > 1000),
    ("retail_banking_aml_alert_triage_stalled_wasteful", "aml_alert_triage",
     lambda r: r["quadrant"] == "Stalled + Wasteful"),
    ("commercial_lending_credit_memo_stalled_efficient", "credit_memo_agent",
     lambda r: r["quadrant"] == "Stalled + Efficient" and r["impact_type"] == "adoption"),
    ("cursor_claude_code_consolidation_candidate_wealth_mgmt", None,
     lambda r: r["source"] == "governance.tool_shape_similarity" and r["lob_id"] == "wealth_management"),
    ("claude_code_cache_expiration_cross_lob", "claude_code",
     lambda r: r["source"] == "anti_pattern.tool_level_rollup" and len(r["lobs"]) == 3),
])
def test_recommendation_arc(arc_name, tool_id, check, arcs):
    assert arc_name in arcs
    recs = recommend(1, 12)["recommendations"]
    matches = [r for r in recs if (tool_id is None or r.get("tool_id") == tool_id) and check(r)]
    assert matches, f"{arc_name}: no recommendation satisfied the check"


def test_all_eight_arcs_have_coverage(manifest):
    """Every planted arc is referenced by at least one test in this module."""
    covered = set(QUADRANT_ARCS) | {
        "claude_code_cache_expiration_cross_lob",
        "cursor_commercial_lending_legitimate_variance",
        "saas_mcp_assist_underutilized_seats",
        "cursor_claude_code_consolidation_candidate_wealth_mgmt",
    }
    all_arcs = {a["arc"] for a in manifest.planted_arcs}
    assert all_arcs <= covered, f"uncovered arcs: {all_arcs - covered}"
