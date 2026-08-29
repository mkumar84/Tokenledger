"""Cost Equation Engine (brief §3.1).

Total Spend = Users
            x Sessions/User
            x Turns/Session
            x Requests/Turn
            x Tokens/Request
            x Price/Token

The six factors are defined so their product reconstructs total spend exactly
(no residual). Also provides sequential driver decomposition between two
periods, attributing the spend delta to adoption, engagement, input-token
workload and output-token workload — again with nothing left unexplained.
"""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import asdict, dataclass
from typing import Any

from ..loader import Session, load_sessions
from ..slicing import (
    SliceKey,
    filter_weeks,
    group_by_slice_week,
    key_payload,
    safe_div,
    validate_group_by,
)

RECONCILE_TOL = 1e-6


@dataclass
class CostBreakdown:
    users: int
    sessions_per_user: float
    turns_per_session: float
    requests_per_turn: float
    tokens_per_request: float
    price_per_token: float
    total_spend_usd: float          # sum of cost_usd in the slice
    reconstructed_spend_usd: float  # product of the six factors
    reconciles: bool
    # supporting raw totals
    sessions: int
    turns: int
    requests: int
    tokens: int

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        for k in (
            "sessions_per_user", "turns_per_session", "requests_per_turn",
            "tokens_per_request", "total_spend_usd", "reconstructed_spend_usd",
        ):
            d[k] = round(d[k], 6)
        d["price_per_token"] = round(d["price_per_token"], 10)
        return d


def _breakdown(sessions: Sequence[Session]) -> CostBreakdown:
    users = len({s.user_id for s in sessions})
    n_sessions = len(sessions)
    turns = sum(s.turn_count for s in sessions)
    requests = sum(s.requests for s in sessions)
    tokens = sum(s.tokens_total for s in sessions)
    total = sum(s.cost_usd for s in sessions)

    spu = safe_div(n_sessions, users)
    tps = safe_div(turns, n_sessions)
    rpt = safe_div(requests, turns)
    tpr = safe_div(tokens, requests)
    ppt = safe_div(total, tokens)

    reconstructed = users * spu * tps * rpt * tpr * ppt
    return CostBreakdown(
        users=users,
        sessions_per_user=spu,
        turns_per_session=tps,
        requests_per_turn=rpt,
        tokens_per_request=tpr,
        price_per_token=ppt,
        total_spend_usd=total,
        reconstructed_spend_usd=reconstructed,
        reconciles=abs(reconstructed - total) <= max(RECONCILE_TOL, total * 1e-9),
        sessions=n_sessions,
        turns=turns,
        requests=requests,
        tokens=tokens,
    )


def cost_equation(
    group_by: str,
    week_from: int | None = None,
    week_to: int | None = None,
    sessions: Sequence[Session] | None = None,
) -> dict[str, Any]:
    """Per-week six-term cost decomposition for every slice."""
    dims = validate_group_by(group_by)
    rows = filter_weeks(sessions if sessions is not None else load_sessions(), week_from, week_to)
    buckets = group_by_slice_week(rows, dims)

    slices: dict[str, list[dict[str, Any]]] = {}
    per_slice_key: dict[SliceKey, list[dict[str, Any]]] = {}
    for (key, week), sess in sorted(buckets.items(), key=lambda kv: (kv[0][0], kv[0][1])):
        bd = _breakdown(sess).to_dict()
        bd["week"] = week
        bd.update(key_payload(key, dims))
        per_slice_key.setdefault(key, []).append(bd)

    result_slices = []
    for key, weeks in per_slice_key.items():
        result_slices.append({
            **key_payload(key, dims),
            "weeks": sorted(weeks, key=lambda r: r["week"]),
        })

    return {
        "engine": "cost_equation",
        "group_by": group_by,
        "week_from": week_from,
        "week_to": week_to,
        "equation": "Users x Sessions/User x Turns/Session x Requests/Turn x Tokens/Request x Price/Token",
        "slices": result_slices,
    }


# --- driver decomposition -------------------------------------------------

@dataclass
class _PeriodFactors:
    users: float
    sessions_per_user: float
    input_cost_per_session: float
    output_cost_per_session: float
    total_spend_usd: float
    sessions: int


def _period_factors(sessions: Sequence[Session]) -> _PeriodFactors:
    users = len({s.user_id for s in sessions})
    n = len(sessions)
    in_cost = sum(s.input_cost_usd for s in sessions)
    out_cost = sum(s.output_cost_usd for s in sessions)
    return _PeriodFactors(
        users=users,
        sessions_per_user=safe_div(n, users),
        input_cost_per_session=safe_div(in_cost, n),
        output_cost_per_session=safe_div(out_cost, n),
        total_spend_usd=in_cost + out_cost,
        sessions=n,
    )


def driver_decomposition(
    group_by: str,
    period_a: tuple[int, int],
    period_b: tuple[int, int],
    sessions: Sequence[Session] | None = None,
) -> dict[str, Any]:
    """Attribute the spend delta between two week-ranges, per slice.

    Sequential (waterfall) attribution over
    ``spend = users x sessions/user x (input$/session + output$/session)``:

      1. adoption          (delta users,          other factors at A)
      2. engagement        (delta sessions/user,  users at B, cost/session at A)
      3. input workload    (delta input$/session, users & spu at B)
      4. output workload   (delta output$/session, users & spu at B)

    The four effects sum to ``spend_b - spend_a`` exactly; residual is 0.
    """
    dims = validate_group_by(group_by)
    all_sessions = sessions if sessions is not None else load_sessions()

    a_rows = filter_weeks(all_sessions, *period_a)
    b_rows = filter_weeks(all_sessions, *period_b)

    from ..slicing import group as _group

    a_groups = _group(a_rows, dims)
    b_groups = _group(b_rows, dims)

    out_slices = []
    for key in sorted(set(a_groups) | set(b_groups)):
        a = _period_factors(a_groups.get(key, []))
        b = _period_factors(b_groups.get(key, []))

        cost_per_session_a = a.input_cost_per_session + a.output_cost_per_session

        adoption = (b.users - a.users) * a.sessions_per_user * cost_per_session_a
        engagement = b.users * (b.sessions_per_user - a.sessions_per_user) * cost_per_session_a
        input_workload = b.users * b.sessions_per_user * (
            b.input_cost_per_session - a.input_cost_per_session
        )
        output_workload = b.users * b.sessions_per_user * (
            b.output_cost_per_session - a.output_cost_per_session
        )

        total_delta = b.total_spend_usd - a.total_spend_usd
        attributed = adoption + engagement + input_workload + output_workload

        out_slices.append({
            **key_payload(key, dims),
            "spend_a_usd": round(a.total_spend_usd, 4),
            "spend_b_usd": round(b.total_spend_usd, 4),
            "delta_usd": round(total_delta, 4),
            "drivers": {
                "adoption_users_usd": round(adoption, 4),
                "engagement_sessions_per_user_usd": round(engagement, 4),
                "input_token_workload_usd": round(input_workload, 4),
                "output_token_workload_usd": round(output_workload, 4),
            },
            "residual_usd": round(total_delta - attributed, 8),
        })

    return {
        "engine": "cost_equation.driver_decomposition",
        "group_by": group_by,
        "period_a_weeks": list(period_a),
        "period_b_weeks": list(period_b),
        "slices": out_slices,
    }
