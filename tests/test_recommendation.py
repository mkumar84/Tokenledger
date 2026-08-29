import pytest

from tokenledger.engines.recommendation import recommend


@pytest.fixture(scope="module")
def recs():
    return recommend(1, 12)


def test_every_recommendation_is_complete(recs):
    for r in recs["recommendations"]:
        assert r["owner"], f"ambiguous owner: {r['title']}"
        assert r["impact_type"] in ("dollar", "adoption", "both")
        if r["impact_type"] in ("dollar", "both"):
            assert r["dollar_impact_usd"] is not None
        if r["impact_type"] in ("adoption", "both"):
            assert r["adoption_impact"]
        assert r["remediation"] and r["remediation"] != r.get("title")
        assert "rank" in r


def test_ranked_by_priority(recs):
    scores = []
    for r in recs["recommendations"]:
        scores.append((r.get("dollar_impact_per_week_usd") or 0)
                      + (r.get("adoption_move_estimate") or 0) * 1000)
    assert scores == sorted(scores, reverse=True)


def test_materiality_gate_suppresses_immaterial(recs):
    assert recs["suppressed"]
    for s in recs["suppressed"]:
        assert "suppressed_reason" in s


def test_no_regression_check_present_and_passes_here(recs):
    chk = recs["no_regression_check"]
    assert "downgrade_unsafe" in chk
    # efficient-small tier is not worse than frontier in this dataset
    assert chk["downgrade_unsafe"] is False


def test_arc_saas_seat_consolidation_recommended(recs):
    r = next(x for x in recs["recommendations"] if x["tool_id"] == "saas_mcp_assist")
    assert r["source"] == "adoption.seat_utilization"
    assert r["dollar_impact_usd"] > 1000
    assert r["owner"] == "Group Platform Eng"


def test_arc_aml_deprecation_recommended(recs):
    r = next(x for x in recs["recommendations"]
             if x["tool_id"] == "aml_alert_triage" and "eprecat" in x["title"])
    assert r["quadrant"] == "Stalled + Wasteful"
    assert r["owner"] == "Retail Banking AI Lead"


def test_arc_credit_memo_enablement_recommended(recs):
    r = next(x for x in recs["recommendations"]
             if x["tool_id"] == "credit_memo_agent")
    assert r["quadrant"] == "Stalled + Efficient"
    assert r["impact_type"] == "adoption"
    assert r["owner"] == "Commercial Lending AI Lead"


def test_arc_claude_code_cross_lob_platform_fix_recommended(recs):
    r = next(x for x in recs["recommendations"]
             if x["source"] == "anti_pattern.tool_level_rollup" and x["tool_id"] == "claude_code")
    assert r["lobs"] and len(r["lobs"]) == 3
    assert r["owner"] == "Group Platform Eng"


def test_arc_wealth_consolidation_recommended(recs):
    r = next(x for x in recs["recommendations"]
             if x["source"] == "governance.tool_shape_similarity")
    assert r["lob_id"] == "wealth_management"
    assert r["evidence"]["mean_axis_relative_diff"] < 0.1
