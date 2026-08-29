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


def test_wealth_portfolio_summarizer_is_growing(arcs):
    """Arc 3: reference implementation — adoption climbs."""
    res = adoption("lob_tool", 1, 12)
    sl = next(s for s in res["slices"]
             if s["lob_id"] == "wealth_management" and s["tool_id"] == "portfolio_summarizer")
    first = next(w["wau"] for w in sl["weeks"] if w["week"] == 1)
    last = next(w["wau"] for w in sl["weeks"] if w["week"] == 12)
    assert last > first * 2
