import pytest

from tokenledger.engines.cost import cost_equation, driver_decomposition


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
    for sl in res["slices"]:
        assert sl["residual_usd"] == pytest.approx(0.0, abs=1e-6)
        d = sl["drivers"]
        attributed = sum(d.values())
        assert attributed == pytest.approx(sl["delta_usd"], abs=1e-3)


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
