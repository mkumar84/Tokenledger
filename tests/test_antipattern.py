import pytest

from tokenledger.engines.antipattern import detect


def _all_lob_findings(res):
    return [f for fs in res["lob_level_findings"].values() for f in fs]


def test_findings_tagged_with_both_dimensions():
    res = detect("lob", 1, 12)
    for f in _all_lob_findings(res):
        assert f["lob_id"] and f["tool_id"]


def test_bad_group_by_rejected():
    with pytest.raises(ValueError):
        detect("lob_tool", 1, 12)


def test_arc_claude_code_cache_expiration_collapses_to_one_tool_finding(arcs):
    """Arc 5: cache churn in 3 of 4 LOBs -> ONE tool-level finding, not three."""
    arc = arcs["claude_code_cache_expiration_cross_lob"]
    res = detect("tool", 1, 12)

    rollups = [
        f for f in res["tool_level_findings"].get("claude_code", [])
        if f.get("scope") == "tool_level_rollup" and f["category"] == "cache_expiration_churn"
    ]
    assert len(rollups) == 1
    r = rollups[0]
    assert sorted(r["lobs"]) == sorted(arc["lobs"])
    assert r["lob_count"] == 3
    assert r["week_from"] == 1 and r["week_to"] <= 8
    assert r["owner"] == "Group Platform Eng"

    # the rolled-up per-LOB findings must NOT also appear as standalone lob findings
    standalone = [
        f for f in _all_lob_findings(res)
        if f["tool_id"] == "claude_code" and f["category"] == "cache_expiration_churn"
        and not f["rolled_up_into_tool_finding"]
    ]
    assert standalone == []


def test_arc_cursor_commercial_lending_legitimate_variance_not_flagged(arcs):
    """Arc 8: high tokens in commercial_lending cursor, but good outcomes ->
    excluded from waste findings, surfaced as legitimate variance."""
    res = detect("lob", 1, 12)

    waste = [
        f for f in _all_lob_findings(res)
        if f["lob_id"] == "commercial_lending" and f["tool_id"] == "cursor"
        and f["category"] == "context_window_bloat"
    ]
    assert waste == []

    excluded = [
        x for x in res["legitimate_variance_exclusions"]
        if x["lob_id"] == "commercial_lending" and x["tool_id"] == "cursor"
    ]
    assert excluded, "expected a legitimate-variance exclusion for cursor/commercial_lending"


def test_arc_retail_banking_aml_is_wasteful(arcs):
    """Arc 4: AML alert triage stays wasteful — zero-outcome + cache churn."""
    res = detect("lob", 1, 12)
    aml = [f for f in _all_lob_findings(res) if f["tool_id"] == "aml_alert_triage"]
    cats = {f["category"] for f in aml}
    assert "zero_outcome_sessions" in cats


def test_arc_insurance_claims_triage_wasteful_early_then_resolves(arcs):
    """Arc 1: waste findings concentrate in weeks 1-6, gone by weeks 9-12."""
    early = detect("lob", 1, 6)
    late = detect("lob", 9, 12)

    def claims(res):
        return {
            f["category"] for f in _all_lob_findings(res)
            if f["tool_id"] == "claims_triage_agent" and f["lob_id"] == "insurance"
        }

    early_cats = claims(early)
    late_cats = claims(late)
    assert {"cache_expiration_churn", "zero_outcome_sessions"} & early_cats
    assert "cache_expiration_churn" not in late_cats
    assert "zero_outcome_sessions" not in late_cats


def test_prompt_init_overhead_is_declared_na():
    res = detect("lob", 1, 12)
    assert "prompt_initialization_overhead" in res["notes"]
    assert not any(
        f["category"] == "prompt_initialization_overhead" for f in _all_lob_findings(res)
    )
