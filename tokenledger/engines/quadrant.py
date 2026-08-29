"""Quadrant classification: Growing/Stalled x Efficient/Wasteful (brief §3.4).

Combines WoW adoption growth (Adoption Engine) with cost-per-session level and
trend (Cost Equation Engine) for the same slice over a week range.
"""
from __future__ import annotations

from collections.abc import Sequence
from statistics import fmean
from typing import Any

from ..loader import Manifest, Session, load_manifest, load_sessions
from ..slicing import filter_weeks, safe_div

# Normalised WAU-penetration slope per week (slope of WAU/total-addressable-users
# regressed on week, divided by the mean), measured over the post-onboarding
# window (week >= ONBOARDING_COMPLETE_WEEK) when the range is long enough, so the
# cohort ramp — identical across slices, done by ~wk 9 — is not mistaken for
# adoption growth. Calibrated to separate the planted arcs.
GROWTH_RATE_THRESHOLD = 0.045
ONBOARDING_COMPLETE_WEEK = 7
ZERO_OUTCOME_WASTEFUL = 0.22
COST_PER_SESSION_PEER_MULT = 1.5  # vs peer p60
LOW_CACHE_WASTEFUL = 0.40


def _linfit_slope(xs: Sequence[float], ys: Sequence[float]) -> float:
    n = len(xs)
    if n < 2:
        return 0.0
    mx = fmean(xs)
    my = fmean(ys)
    denom = sum((x - mx) ** 2 for x in xs)
    if denom == 0:
        return 0.0
    return sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / denom


def _weekly(rows: Sequence[Session]) -> dict[int, list[Session]]:
    out: dict[int, list[Session]] = {}
    for s in rows:
        out.setdefault(s.week, []).append(s)
    return out


def _penetration_growth_rate(
    weekly: dict[int, list[Session]], addressable_users: int
) -> tuple[float, list[tuple[int, float]]]:
    """Normalised slope of WAU-penetration (WAU / addressable users) vs week.

    ``addressable_users`` is the fixed total-addressable population for the
    slice (from the manifest roster), so cohort onboarding — which completes by
    ~week 9 and is identical across slices — no longer masquerades as adoption
    growth. Returns (slope / mean_penetration, series).
    """
    weeks = sorted(weekly)
    denom = addressable_users or 1
    series = [
        (w, safe_div(len({s.user_id for s in weekly[w]}), denom)) for w in weeks
    ]
    if len(series) < 2:
        return 0.0, series
    fit = [pt for pt in series if pt[0] >= ONBOARDING_COMPLETE_WEEK]
    if len(fit) < 3:
        fit = series
    slope = _linfit_slope([w for w, _ in fit], [p for _, p in fit])
    mean_p = fmean(p for _, p in fit) or 1.0
    return slope / mean_p, series


def _cost_per_session_series(weekly: dict[int, list[Session]]) -> list[tuple[int, float]]:
    return [
        (w, safe_div(sum(s.cost_usd for s in weekly[w]), len(weekly[w])))
        for w in sorted(weekly)
    ]


def classify(
    lob_id: str | None,
    tool_id: str | None,
    week_from: int,
    week_to: int,
    sessions: Sequence[Session] | None = None,
    manifest: Manifest | None = None,
) -> dict[str, Any]:
    all_rows = sessions if sessions is not None else load_sessions()
    manifest = manifest or load_manifest()
    scoped = filter_weeks(all_rows, week_from, week_to)

    def match(s: Session) -> bool:
        return (lob_id is None or s.lob_id == lob_id) and (tool_id is None or s.tool_id == tool_id)

    rows = [s for s in scoped if match(s)]
    if not rows:
        return {"lob_id": lob_id, "tool_id": tool_id, "week_from": week_from,
                "week_to": week_to, "quadrant": None, "reason": "no sessions in range"}

    if lob_id is not None:
        addressable = manifest.users_per_lob.get(lob_id, len({s.user_id for s in all_rows}))
    else:
        lobs_using = {s.lob_id for s in all_rows if tool_id is None or s.tool_id == tool_id}
        addressable = sum(manifest.users_per_lob.get(l, 0) for l in lobs_using) or \
            len({s.user_id for s in all_rows})

    weekly = _weekly(rows)
    growth, pen_series = _penetration_growth_rate(weekly, addressable)

    n = len(rows)
    cost_per_session = fmean(s.cost_usd for s in rows)
    zero_rate = safe_div(sum(s.is_zero_outcome for s in rows), n)
    cache = fmean(s.cache_hit_rate for s in rows)

    cps_series = _cost_per_session_series(weekly)
    cps_slope = _linfit_slope([w for w, _ in cps_series], [c for _, c in cps_series])

    # peer baseline: same category of tool (managed agent vs interactive), all LOBs, same weeks
    tgt_agentlike = rows[0].agent_id is not None
    peer_costs = sorted(
        fmean(s.cost_usd for s in grp)
        for grp in _peer_groups(scoped, tgt_agentlike).values()
        if grp
    )
    peer_p60 = peer_costs[int(len(peer_costs) * 0.6)] if peer_costs else cost_per_session

    growing = growth >= GROWTH_RATE_THRESHOLD
    wasteful = (
        zero_rate > ZERO_OUTCOME_WASTEFUL
        or (cost_per_session > peer_p60 * COST_PER_SESSION_PEER_MULT and cache < LOW_CACHE_WASTEFUL)
        or (cps_slope > 0 and cost_per_session > peer_p60 * COST_PER_SESSION_PEER_MULT)
    )

    quadrant = f"{'Growing' if growing else 'Stalled'} + {'Wasteful' if wasteful else 'Efficient'}"
    return {
        "lob_id": lob_id,
        "tool_id": tool_id,
        "week_from": week_from,
        "week_to": week_to,
        "quadrant": quadrant,
        "signals": {
            "penetration_growth_rate_per_week": round(growth, 4),
            "penetration_series": [[w, round(p, 4)] for w, p in pen_series],
            "growing": growing,
            "cost_per_session_usd": round(cost_per_session, 4),
            "cost_per_session_slope": round(cps_slope, 6),
            "peer_p60_cost_per_session_usd": round(peer_p60, 4),
            "zero_outcome_rate": round(zero_rate, 3),
            "cache_hit_rate": round(cache, 3),
            "wasteful": wasteful,
        },
    }


def _peer_groups(scoped: Sequence[Session], agentlike: bool) -> dict[tuple[str, str], list[Session]]:
    out: dict[tuple[str, str], list[Session]] = {}
    for s in scoped:
        if (s.agent_id is not None) != agentlike:
            continue
        out.setdefault((s.lob_id, s.tool_id), []).append(s)
    return out


def classify_batch(
    lob_ids: list[str] | None,
    tool_ids: list[str] | None,
    week_from: int,
    week_to: int,
    sessions: Sequence[Session] | None = None,
    manifest: Manifest | None = None,
) -> dict[str, Any]:
    """Quadrant for many slices in one call.

    - ``lob_ids`` and ``tool_ids`` both ``None`` (bare ``/quadrant``): every LOB
      (LOB-level, ``tool_id`` null), every tool (tool-level, ``lob_id`` null),
      and every (lob, tool) cell that has sessions.
    - one list given: those LOBs (LOB-level) or those tools (tool-level).
    - both lists given: the cross product of cells.

    Result rows are the same shape ``classify`` returns, collected under
    ``results``. Single-slice callers keep using ``classify`` directly.
    """
    all_rows = sessions if sessions is not None else load_sessions()
    manifest = manifest or load_manifest()

    present_lobs = sorted({s.lob_id for s in all_rows})
    present_tools = sorted({s.tool_id for s in all_rows})
    present_cells = sorted({(s.lob_id, s.tool_id) for s in all_rows})

    targets: list[tuple[str | None, str | None]] = []
    if lob_ids is None and tool_ids is None:
        targets += [(lob, None) for lob in present_lobs]
        targets += [(None, tool) for tool in present_tools]
        targets += list(present_cells)
    elif lob_ids is not None and tool_ids is not None:
        targets += [(lob, tool) for lob in lob_ids for tool in tool_ids]
    elif lob_ids is not None:
        targets += [(lob, None) for lob in lob_ids]
    else:  # tool_ids is not None
        targets += [(None, tool) for tool in tool_ids]

    results = [
        classify(lob, tool, week_from, week_to, sessions=all_rows, manifest=manifest)
        for lob, tool in targets
    ]
    return {
        "week_from": week_from,
        "week_to": week_to,
        "count": len(results),
        "results": results,
    }
