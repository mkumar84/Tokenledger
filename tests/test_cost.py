import pytest

from tokenledger.engines.cost import cost_equation, driver_decomposition
from tokenledger.engines.recommendation import recommend


@pytest.mark.parametrize("group_by", ["lob", "tool", "lob_tool"])
def test_six_terms_reconstruct_total_spend(group_by):
    res = cost_equation(group_by, 1, 12)
    assert res["slices"]
    for sl in res["slices"]:
        for wk in sl["weeks"]:
            factors = (
                wk["users"] * wk["sessions_per_user"] * wk["turns_per_session"]
                * wk["requests_per_turn"] * wk["tokens_per_request"] * wk["price_per_token"]
            )
            assert wk["reconciles"] is True
            assert factors == pytest.approx(wk["total_spend_usd"], rel=1e-6, abs=1e-4)


def test_group_by_is_one_code_path_three_shapes():
    lob = cost_equation("lob", 1, 12)
    tool = cost_equation("tool", 1, 12)
    lob_tool = cost_equation("lob_tool", 1, 12)
    assert {tuple(sorted(s.keys())) for s in lob["slices"]}  # lob_id + weeks
    assert all("tool_id" in s for s in tool["slices"])
    assert all("lob_id" in s and "tool_id" in s for s in lob_tool["slices"])


def test_total_spend_is_invariant_to_grouping():
    def total(res):
        return sum(w["total_spend_usd"] for s in res["slices"] for w in s["weeks"])

    a = total(cost_equation("lob", 1, 12))
    b = total(cost_equation("tool", 1, 12))
    c = total(cost_equation("lob_tool", 1, 12))
    assert a == pytest.approx(b, rel=1e-9)
    assert a == pytest.approx(c, rel=1e-9)


def test_bad_group_by_rejected():
    with pytest.raises(ValueError):
        cost_equation("region", 1, 12)


@pytest.mark.parametrize("group_by", ["lob", "tool", "lob_tool"])
def test_driver_decomposition_has_no_residual(group_by):
    res = driver_decomposition(group_by, (1, 3), (10, 12))
    assert res["slices"]
    consumption_keys = res["consumption_drivers"]
    for sl in res["slices"]:
        assert sl["residual_usd"] == pytest.approx(0.0, abs=1e-6)
        d = sl["drivers"]
        # the FOUR consumption drivers reconstruct the consumption delta exactly
        assert sum(d[k] for k in consumption_keys) == pytest.approx(sl["delta_usd"], abs=1e-3)
        # all five reconstruct total_delta_usd
        assert sum(d.values()) == pytest.approx(sl["total_delta_usd"], abs=1e-3)


def test_driver_license_bucket_zero_for_equal_length_periods():
    res = driver_decomposition("lob", (1, 4), (9, 12))  # both 4 weeks
    assert res["fleet_license_delta_usd"] == 0.0
    for sl in res["slices"]:
        assert sl["drivers"]["license_usd"] == 0.0
        assert sl["total_delta_usd"] == pytest.approx(sl["delta_usd"], abs=1e-9)


def test_driver_license_bucket_nonzero_when_periods_differ_in_length():
    res = driver_decomposition("lob", (1, 3), (9, 12))  # 3 weeks vs 4 weeks
    assert res["fleet_license_delta_usd"] > 0  # one extra week of seat fees in period B
    shares = sum(sl["drivers"]["license_usd"] for sl in res["slices"])
    assert shares == pytest.approx(res["fleet_license_delta_usd"], abs=0.05)


# --- Patch 5: consumption + license reconciliation --------------------------

@pytest.mark.parametrize("group_by", ["lob", "tool", "lob_tool"])
def test_total_spend_is_consumption_plus_license(group_by):
    res = cost_equation(group_by, 1, 12)
    assert res["total_spend_usd"] == pytest.approx(
        res["consumption_spend_usd"] + res["license_spend_usd"], abs=0.01)
    assert res["consumption_reconciles"] is True
    # consumption still equals the sum of the six-term slice-week totals
    slice_total = sum(w["total_spend_usd"] for sl in res["slices"] for w in sl["weeks"])
    assert slice_total == pytest.approx(res["consumption_spend_usd"], abs=0.01)
    # license detail sums to the top-line license figure
    assert sum(d["license_spend_usd"] for d in res["license_spend_detail"]) == pytest.approx(
        res["license_spend_usd"], abs=0.02)


def test_license_spend_scales_with_window_length():
    full = cost_equation("lob", 1, 12)["license_spend_usd"]
    half = cost_equation("lob", 1, 6)["license_spend_usd"]
    assert full == pytest.approx(half * 2, rel=1e-6)


def test_license_spend_uses_monthly_to_weekly_conversion():
    res = cost_equation("tool", 1, 12)
    saas = next(d for d in res["license_spend_detail"] if d["tool_id"] == "saas_mcp_assist")
    # 25 seats/LOB x 4 LOBs x ($60/mo / 4.345) x 12 weeks
    assert saas["seats_total"] == 100
    assert saas["cost_per_seat_month_usd"] == 60
    assert saas["license_spend_usd"] == pytest.approx(100 * (60 / 4.345) * 12, abs=1.0)


@pytest.mark.parametrize("window", [(1, 12), (1, 6), (7, 12), (3, 9)])
def test_recoverable_spend_never_exceeds_total_spend(window):
    """THE invariant Patch 5 exists to enforce: no recommendation can claim to
    recover more dollars than the total spend of the same window. This is the
    check that would have caught the original $4.5k/wk-vs-$108-total bug."""
    wf, wt = window
    total = cost_equation("lob", wf, wt)["total_spend_usd"]
    recs = recommend(wf, wt)["recommendations"]
    recoverable = sum(r["dollar_impact_usd"] or 0 for r in recs)
    assert recoverable <= total + 1e-6, (
        f"window {window}: recoverable ${recoverable:.2f} > total spend ${total:.2f}"
    )


def test_invariant_holds_for_each_seat_license_recommendation():
    """Across every seat/license-related finding individually, and their sum."""
    total = cost_equation("lob", 1, 12)["total_spend_usd"]
    recs = recommend(1, 12)["recommendations"]
    seat_recs = [r for r in recs if r["source"] in
                 ("adoption.seat_utilization", "governance.tool_shape_similarity")]
    assert seat_recs
    for r in seat_recs:
        assert (r["dollar_impact_usd"] or 0) <= total
    assert sum(r["dollar_impact_usd"] or 0 for r in seat_recs) <= total


def test_driver_decomposition_attributes_claims_triage_savings_to_workload():
    """Arc 1: the claims_triage fix (weeks 1-3 vs 10-12) cuts spend; the saving
    should land on token workload, not on users (adoption keeps growing)."""
    res = driver_decomposition("lob_tool", (1, 3), (10, 12))
    sl = next(s for s in res["slices"]
             if s["lob_id"] == "insurance" and s["tool_id"] == "claims_triage_agent")
    d = sl["drivers"]
    assert sl["delta_usd"] < 0  # net cheaper despite more users
    assert d["adoption_users_usd"] > 0  # more users pushed spend UP
    assert d["input_token_workload_usd"] + d["output_token_workload_usd"] < 0  # workload fix pulled it DOWN
    assert (d["input_token_workload_usd"] + d["output_token_workload_usd"]) < d["adoption_users_usd"]
