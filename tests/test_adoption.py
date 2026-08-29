import pytest

from tokenledger.engines.adoption import adoption


@pytest.mark.parametrize("group_by", ["lob", "tool", "lob_tool"])
def test_shapes_and_required_metrics(group_by):
    res = adoption(group_by, 1, 12)
    assert res["slices"]
    for sl in res["slices"]:
        for wk in sl["weeks"]:
            assert set(wk) >= {
                "week", "wau", "wow_growth_rate", "sessions_per_user",
                "retention_rate", "activation_rate", "non_human_session_share",
            }
            assert wk["non_human_session_share"] == 0.0  # stubbed, not fabricated


def test_wau_and_growth_consistent():
    res = adoption("lob", 1, 12)
    for sl in res["slices"]:
        weeks = {w["week"]: w for w in sl["weeks"]}
        for w in range(2, 13):
            cur, prev = weeks[w], weeks[w - 1]
            if prev["wau"]:
                expected = (cur["wau"] - prev["wau"]) / prev["wau"]
                assert cur["wow_growth_rate"] == pytest.approx(expected, abs=1e-4)


def test_seat_utilization_only_for_tool_slices():
    lob = adoption("lob", 1, 12)
    assert all("seat_utilization" not in w for sl in lob["slices"] for w in sl["weeks"])

    tool = adoption("tool", 1, 12)
    saas = next(s for s in tool["slices"] if s["tool_id"] == "saas_mcp_assist")
    for w in saas["weeks"]:
        su = w["seat_utilization"]
        assert su["licensed_seats"] == 100  # 25/LOB x 4 LOBs
        assert su["wasted_seat_cost_usd"] == pytest.approx(su["unused_seats"] * 60, abs=0.01)


def test_cursor_seat_utilization_computed_from_registry_field():
    """Phase 1 patch: cursor now declares seats_per_lob (20) in tool_registry,
    so it gets the same seat-utilization + wasted-$ treatment as saas_mcp_assist
    — no name special-casing."""
    tool = adoption("tool", 1, 12)
    cursor = next(s for s in tool["slices"] if s["tool_id"] == "cursor")
    for w in cursor["weeks"]:
        su = w["seat_utilization"]
        assert su["licensed_seats"] == 80  # 20/LOB x 4 LOBs
        assert su["active_users"] <= su["licensed_seats"] or su["utilization_pct"] > 100
        assert su["cost_per_seat_usd"] == 40
        assert su["wasted_seat_cost_usd"] == pytest.approx(su["unused_seats"] * 40, abs=0.01)
        assert "note" not in su  # denominator is known now

    lob_tool = adoption("lob_tool", 1, 12)
    for sl in (s for s in lob_tool["slices"] if s["tool_id"] == "cursor"):
        assert all(w["seat_utilization"]["licensed_seats"] == 20 for w in sl["weeks"])


def test_arc_saas_mcp_assist_underutilized_seats(arcs):
    """Arc 6: flat, low seat utilization group-wide."""
    arc = arcs["saas_mcp_assist_underutilized_seats"]
    res = adoption("tool", *arc["week_range"])
    saas = next(s for s in res["slices"] if s["tool_id"] == "saas_mcp_assist")
    utils = [w["seat_utilization"]["utilization_pct"] for w in saas["weeks"]]
    avg = sum(utils) / len(utils)
    assert avg < 55  # "30%"ish, definitely under-utilized
    assert max(utils) - min(utils) < 35  # roughly flat, no growth trend
    # wasted-seat dollars are material
    assert saas["weeks"][-1]["seat_utilization"]["wasted_seat_cost_usd"] > 1000


def test_arc_commercial_lending_credit_memo_low_engagement(arcs):
    """Arc 2: stalled adoption — low sessions/user, weak growth."""
    res = adoption("lob_tool", 1, 12)
    sl = next(s for s in res["slices"]
             if s["lob_id"] == "commercial_lending" and s["tool_id"] == "credit_memo_agent")
    late = [w for w in sl["weeks"] if w["week"] >= 9]
    growths = [w["wow_growth_rate"] for w in late if w["wow_growth_rate"] is not None]
    assert sum(growths) / len(growths) < 0.05  # essentially flat once onboarded


@pytest.mark.parametrize("group_by", ["lob", "tool", "lob_tool"])
def test_funnel_is_monotonically_non_increasing(group_by):
    """Eligible >= Onboarded >= Activated >= Habitual >= Power user for every
    slice, by construction (each stage is a subset of the previous)."""
    res = adoption(group_by, 1, 12)
    for sl in res["slices"]:
        f = sl["funnel"]
        stages = [f["eligible"], f["onboarded"], f["activated"], f["habitual"], f["power_user"]]
        assert stages == sorted(stages, reverse=True), f"{sl}: {stages}"
        assert f["as_of_week"] == 12


def test_funnel_reference_arc_has_full_five_stages(arcs):
    """Arc 3: wealth_management portfolio_summarizer is the healthy reference —
    it should carry users all the way down the funnel to a non-zero power tier."""
    res = adoption("lob_tool", 1, 12)
    sl = next(s for s in res["slices"]
             if s["lob_id"] == "wealth_management" and s["tool_id"] == "portfolio_summarizer")
    f = sl["funnel"]
    assert f["eligible"] == 18  # wealth_management roster
    assert f["onboarded"] >= f["activated"] >= f["habitual"] >= 1
    assert f["power_user"] >= 1


def test_funnel_stalled_arc_thins_out(arcs):
    """Arc 4: retail_banking aml_alert_triage is stalled — the funnel should
    collapse (no habitual users)."""
    res = adoption("lob_tool", 1, 12)
    sl = next(s for s in res["slices"]
             if s["lob_id"] == "retail_banking" and s["tool_id"] == "aml_alert_triage")
    f = sl["funnel"]
    assert f["onboarded"] < f["eligible"]   # weak onboarding
    assert f["habitual"] == 0
    assert f["power_user"] == 0


def test_wealth_portfolio_summarizer_is_growing(arcs):
    """Arc 3: reference implementation — adoption climbs."""
    res = adoption("lob_tool", 1, 12)
    sl = next(s for s in res["slices"]
             if s["lob_id"] == "wealth_management" and s["tool_id"] == "portfolio_summarizer")
    first = next(w["wau"] for w in sl["weeks"] if w["week"] == 1)
    last = next(w["wau"] for w in sl["weeks"] if w["week"] == 12)
    assert last > first * 2
