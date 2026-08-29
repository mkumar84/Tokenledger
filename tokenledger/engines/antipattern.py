"""Anti-Pattern Detector (brief §3.3).

Scores each (lob_id, tool_id, week) aggregate against seven categories, tags
every finding with BOTH ``lob_id`` and ``tool_id``, merges consecutive weeks
into ranges, then:

  * rolls up any anti-pattern present in >=3 of the 4 LOBs for the same tool +
    overlapping week-range into ONE tool-level finding (owner = tool owner);
  * excludes legitimate workload variance -- a high-token slice whose outcome
    rate is normal is a different workload, not waste (deciding signal is
    outcome rate / cost-per-successful-outcome, never raw token volume).

``group_by`` ("lob" | "tool") selects which view is primary in the response;
both views are always computed.
"""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from statistics import fmean
from typing import Any

from ..loader import Manifest, Session, load_manifest, load_sessions
from ..reference import CACHE_DISCOUNT, FRONTIER_MODELS, MODEL_PRICING
from ..slicing import contiguous_ranges, filter_weeks, merge_range, ranges_overlap, safe_div

# --- thresholds ----------------------------------------------------------

LOW_TURN_COUNT = 5
BLOAT_TOKENS_IN_MULT = 1.6
CACHE_CHURN_RATIO = 0.7          # bucket cache < 0.7x fleet baseline
CACHE_CHURN_ABS_MARGIN = 0.10    # and at least 0.10 below baseline
CHATTY_RPT_MULT = 1.3
REASONING_MISMATCH_SHARE = 0.35
MODEL_ROUTING_SHARE = 0.35
ZERO_OUTCOME_ABS = 0.25
ZERO_OUTCOME_MULT = 1.5
LEGIT_VARIANCE_ZERO_CEIL = 0.15  # outcome rate this good => not waste
LEGIT_VARIANCE_BASELINE_MULT = 1.25
ROLLUP_MIN_LOBS = 3

CATEGORIES = (
    "suboptimal_model_routing",
    "context_window_bloat",
    "cache_expiration_churn",
    "prompt_initialization_overhead",  # n/a at session level in this dataset
    "chatty_tool_use",
    "reasoning_effort_mismatch",
    "zero_outcome_sessions",
)


@dataclass
class ToolBaseline:
    tool_id: str
    sessions: int
    tokens_in: float
    tokens_out: float
    cache_hit_rate: float
    requests_per_turn: float
    zero_outcome_rate: float
    cost_per_session: float


def _tool_baselines(sessions: Sequence[Session]) -> dict[str, ToolBaseline]:
    by_tool: dict[str, list[Session]] = {}
    for s in sessions:
        by_tool.setdefault(s.tool_id, []).append(s)
    out: dict[str, ToolBaseline] = {}
    for tool_id, rows in by_tool.items():
        n = len(rows)
        out[tool_id] = ToolBaseline(
            tool_id=tool_id,
            sessions=n,
            tokens_in=fmean(s.tokens_in for s in rows),
            tokens_out=fmean(s.tokens_out for s in rows),
            cache_hit_rate=fmean(s.cache_hit_rate for s in rows),
            requests_per_turn=fmean(s.requests_per_turn for s in rows),
            zero_outcome_rate=safe_div(sum(s.is_zero_outcome for s in rows), n),
            cost_per_session=fmean(s.cost_usd for s in rows),
        )
    return out


@dataclass
class Finding:
    category: str
    lob_id: str
    tool_id: str
    week_from: int
    week_to: int
    severity: str
    dollar_impact_usd: float | None
    metric: dict[str, Any]
    detail: str
    rolled_up: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "category": self.category,
            "lob_id": self.lob_id,
            "tool_id": self.tool_id,
            "week_from": self.week_from,
            "week_to": self.week_to,
            "severity": self.severity,
            "dollar_impact_usd": (
                round(self.dollar_impact_usd, 2) if self.dollar_impact_usd is not None else None
            ),
            "metric": self.metric,
            "detail": self.detail,
            "rolled_up_into_tool_finding": self.rolled_up,
        }


@dataclass
class _WeekHit:
    category: str
    week: int
    dollar_impact_usd: float | None
    metric: dict[str, Any]
    detail: str
    legitimate_variance: bool = False


# --- per (lob, tool, week) scoring -------------------------------------

def _score_bucket(
    rows: Sequence[Session], base: ToolBaseline
) -> list[_WeekHit]:
    hits: list[_WeekHit] = []
    n = len(rows)
    if n == 0:
        return hits

    mean_tokens_in = fmean(s.tokens_in for s in rows)
    mean_cache = fmean(s.cache_hit_rate for s in rows)
    mean_rpt = fmean(s.requests_per_turn for s in rows)
    zero_rate = safe_div(sum(s.is_zero_outcome for s in rows), n)
    week = rows[0].week

    outcomes_normal = zero_rate <= max(
        LEGIT_VARIANCE_ZERO_CEIL, base.zero_outcome_rate * LEGIT_VARIANCE_BASELINE_MULT
    )

    # 1. suboptimal model routing -------------------------------------
    frontier = [s for s in rows if s.model in FRONTIER_MODELS]
    if frontier:
        low_complexity = [
            s for s in frontier
            if s.turn_count <= LOW_TURN_COUNT
            and s.tokens_out < base.tokens_out * 0.6
            and s.reasoning_effort != "high"
        ]
        share = len(low_complexity) / n
        if share >= MODEL_ROUTING_SHARE:
            saving = sum(
                s.input_cost_usd + s.output_cost_usd
                - _repriced(s, "efficient-small")
                for s in low_complexity
            )
            hits.append(_WeekHit(
                "suboptimal_model_routing", week, max(0.0, saving),
                {"low_complexity_frontier_share": round(share, 3),
                 "sessions": len(low_complexity)},
                f"{share:.0%} of sessions run a frontier model on short, "
                f"low-output work that an efficient-tier model would handle.",
            ))

    # 2. context window bloat ---------------------------------------
    if mean_tokens_in > base.tokens_in * BLOAT_TOKENS_IN_MULT:
        excess = (mean_tokens_in - base.tokens_in) / 1000
        price_in = fmean(MODEL_PRICING.get(s.model, {"input": 0})["input"] for s in rows)
        impact = excess * price_in * n
        hits.append(_WeekHit(
            "context_window_bloat", week, impact,
            {"mean_tokens_in": round(mean_tokens_in),
             "fleet_baseline_tokens_in": round(base.tokens_in),
             "ratio": round(mean_tokens_in / base.tokens_in, 2),
             "zero_outcome_rate": round(zero_rate, 3),
             "fleet_baseline_zero_outcome_rate": round(base.zero_outcome_rate, 3)},
            f"Input tokens/session {mean_tokens_in/base.tokens_in:.1f}x the "
            f"{base.tool_id} fleet baseline.",
            legitimate_variance=outcomes_normal,
        ))

    # 3. cache-expiration churn -------------------------------------
    if (
        mean_cache < base.cache_hit_rate * CACHE_CHURN_RATIO
        and mean_cache < base.cache_hit_rate - CACHE_CHURN_ABS_MARGIN
    ):
        recoverable = base.cache_hit_rate - mean_cache
        extra_cost = 0.0
        for s in rows:
            price_in = MODEL_PRICING.get(s.model, {"input": 0})["input"]
            extra_effective = s.tokens_in * recoverable * CACHE_DISCOUNT
            extra_cost += (extra_effective / 1000) * price_in
        hits.append(_WeekHit(
            "cache_expiration_churn", week, extra_cost,
            {"mean_cache_hit_rate": round(mean_cache, 3),
             "fleet_baseline_cache_hit_rate": round(base.cache_hit_rate, 3)},
            f"Cache hit rate {mean_cache:.0%} vs {base.cache_hit_rate:.0%} fleet "
            f"baseline for {base.tool_id} — context is being re-sent uncached.",
        ))

    # 4. prompt-initialization overhead: n/a at session level -> skip

    # 5. chatty tool-use ------------------------------------------
    if mean_rpt > base.requests_per_turn * CHATTY_RPT_MULT:
        hits.append(_WeekHit(
            "chatty_tool_use", week, None,
            {"mean_requests_per_turn": round(mean_rpt, 2),
             "fleet_baseline": round(base.requests_per_turn, 2)},
            f"Requests/turn {mean_rpt:.1f} vs {base.requests_per_turn:.1f} baseline.",
        ))

    # 6. reasoning-effort mismatch --------------------------------
    mismatched = [
        s for s in rows
        if s.reasoning_effort == "high"
        and s.turn_count <= LOW_TURN_COUNT
        and s.tokens_out < base.tokens_out * 0.6
    ]
    if mismatched and len(mismatched) / n >= REASONING_MISMATCH_SHARE:
        hits.append(_WeekHit(
            "reasoning_effort_mismatch", week, None,
            {"share": round(len(mismatched) / n, 3), "sessions": len(mismatched)},
            f"{len(mismatched)/n:.0%} of sessions request high reasoning effort on "
            f"short, low-output work.",
        ))

    # 7. zero-outcome sessions -----------------------------------
    if zero_rate > max(ZERO_OUTCOME_ABS, base.zero_outcome_rate * ZERO_OUTCOME_MULT):
        wasted = sum(s.cost_usd for s in rows if s.is_zero_outcome)
        hits.append(_WeekHit(
            "zero_outcome_sessions", week, wasted,
            {"zero_outcome_rate": round(zero_rate, 3),
             "fleet_baseline": round(base.zero_outcome_rate, 3),
             "zero_outcome_sessions": sum(s.is_zero_outcome for s in rows)},
            f"{zero_rate:.0%} of sessions ended with no business outcome "
            f"(${wasted:.2f} spent).",
        ))

    return hits


def _repriced(s: Session, model: str) -> float:
    price = MODEL_PRICING[model]
    effective_in = s.tokens_in * (1 - s.cache_hit_rate * CACHE_DISCOUNT)
    return (effective_in / 1000) * price["input"] + (s.tokens_out / 1000) * price["output"]


def _severity(dollar: float | None, metric: dict[str, Any]) -> str:
    if dollar is None:
        return "low"
    if dollar >= 200:
        return "high"
    if dollar >= 50:
        return "medium"
    return "low"


# --- public API --------------------------------------------------------

def detect(
    group_by: str = "lob",
    week_from: int | None = None,
    week_to: int | None = None,
    sessions: Sequence[Session] | None = None,
    manifest: Manifest | None = None,
) -> dict[str, Any]:
    if group_by not in ("lob", "tool"):
        raise ValueError("anti-pattern group_by must be 'lob' or 'tool'")
    manifest = manifest or load_manifest()
    all_rows = sessions if sessions is not None else load_sessions()
    scoped = filter_weeks(all_rows, week_from, week_to)
    baselines = _tool_baselines(all_rows)  # baseline always over full fleet history

    # bucket by (lob, tool, week)
    buckets: dict[tuple[str, str, int], list[Session]] = {}
    for s in scoped:
        buckets.setdefault((s.lob_id, s.tool_id, s.week), []).append(s)

    # (lob, tool, category) -> list[_WeekHit]
    by_lt_cat: dict[tuple[str, str, str], list[_WeekHit]] = {}
    legit_by_key: dict[tuple[str, str, str], list[_WeekHit]] = {}
    for (lob, tool, _week), rows in buckets.items():
        for hit in _score_bucket(rows, baselines[tool]):
            if hit.legitimate_variance:
                legit_by_key.setdefault((hit.category, lob, tool), []).append(hit)
                continue
            by_lt_cat.setdefault((lob, tool, hit.category), []).append(hit)

    legit_variance: list[dict[str, Any]] = []
    for (cat, lob, tool), hits in legit_by_key.items():
        weeks_flagged = sorted(h.week for h in hits)
        for wr in contiguous_ranges(weeks_flagged):
            legit_variance.append({
                "category": cat, "lob_id": lob, "tool_id": tool,
                "week_from": wr[0], "week_to": wr[1],
                "weeks": [w for w in weeks_flagged if wr[0] <= w <= wr[1]],
                "detail": hits[-1].detail + " Outcome rate is normal — treated as "
                          "legitimate workload variance, not waste.",
            })

    # collapse consecutive weeks into ranges -> Finding objects
    lob_findings: list[Finding] = []
    for (lob, tool, cat), hits in by_lt_cat.items():
        hits_by_week = {h.week: h for h in hits}
        for wr in contiguous_ranges(hits_by_week):
            span = [hits_by_week[w] for w in range(wr[0], wr[1] + 1) if w in hits_by_week]
            dollars = [h.dollar_impact_usd for h in span if h.dollar_impact_usd is not None]
            total_dollars = sum(dollars) if dollars else None
            merged_metric = {
                "weeks_flagged": [h.week for h in span],
                "per_week": [{"week": h.week, **h.metric,
                              "dollar_impact_usd": round(h.dollar_impact_usd, 2)
                              if h.dollar_impact_usd is not None else None}
                             for h in span],
            }
            lob_findings.append(Finding(
                category=cat, lob_id=lob, tool_id=tool,
                week_from=wr[0], week_to=wr[1],
                severity=_severity(total_dollars, merged_metric),
                dollar_impact_usd=total_dollars,
                metric=merged_metric,
                detail=span[-1].detail,
            ))

    tool_findings = _rollup(lob_findings, manifest)

    lob_view: dict[str, list[dict[str, Any]]] = {}
    for f in sorted(lob_findings, key=lambda x: (x.lob_id, x.tool_id, -(x.dollar_impact_usd or 0))):
        lob_view.setdefault(f.lob_id, []).append(f.to_dict())

    tool_view: dict[str, list[dict[str, Any]]] = {}
    for f in tool_findings:
        tool_view.setdefault(f["tool_id"], []).append(f)
    # non-rolled-up lob findings also belong to their tool in the tool view
    for f in sorted(lob_findings, key=lambda x: (x.tool_id, x.lob_id)):
        if not f.rolled_up:
            tool_view.setdefault(f.tool_id, []).append(f.to_dict())

    return {
        "engine": "anti_pattern_detector",
        "group_by": group_by,
        "week_from": week_from,
        "week_to": week_to,
        "categories": list(CATEGORIES),
        "primary_view": group_by,
        "lob_level_findings": lob_view,
        "tool_level_findings": tool_view,
        "legitimate_variance_exclusions": legit_variance,
        "notes": {
            "prompt_initialization_overhead": "n/a at session level in this dataset — not scored.",
            "chatty_tool_use": "requests_per_turn has no planted variance in v1; rule active but expected silent.",
        },
    }


def _rollup(lob_findings: list[Finding], manifest: Manifest) -> list[dict[str, Any]]:
    """>=3 of 4 LOBs, same tool+category, overlapping weeks -> one finding."""
    n_lobs = len(manifest.lobs) or 4
    by_tc: dict[tuple[str, str], list[Finding]] = {}
    for f in lob_findings:
        by_tc.setdefault((f.tool_id, f.category), []).append(f)

    rolled: list[dict[str, Any]] = []
    for (tool, cat), group in by_tc.items():
        # cluster by overlapping week-range
        clusters: list[list[Finding]] = []
        for f in sorted(group, key=lambda x: x.week_from):
            placed = False
            for cl in clusters:
                if any(ranges_overlap((f.week_from, f.week_to), (g.week_from, g.week_to)) for g in cl):
                    cl.append(f)
                    placed = True
                    break
            if not placed:
                clusters.append([f])

        for cl in clusters:
            lobs = sorted({f.lob_id for f in cl})
            if len(lobs) < ROLLUP_MIN_LOBS:
                continue
            wr = (min(f.week_from for f in cl), max(f.week_to for f in cl))
            for f in cl:
                f.rolled_up = True
            dollars = [f.dollar_impact_usd for f in cl if f.dollar_impact_usd is not None]
            rolled.append({
                "category": cat,
                "tool_id": tool,
                "scope": "tool_level_rollup",
                "lobs": lobs,
                "lob_count": len(lobs),
                "total_lobs": n_lobs,
                "week_from": wr[0],
                "week_to": wr[1],
                "owner": manifest.tool_owner(tool),
                "dollar_impact_usd": round(sum(dollars), 2) if dollars else None,
                "severity": _severity(sum(dollars) if dollars else None, {}),
                "detail": (
                    f"{cat.replace('_', ' ')} present in {len(lobs)} of {n_lobs} LOBs "
                    f"for {tool} (weeks {wr[0]}-{wr[1]}). One platform-level fix, "
                    f"owner {manifest.tool_owner(tool)}, not {len(lobs)} separate LOB tickets."
                ),
                "rolled_up_lob_findings": [f.to_dict() for f in cl],
            })
    return rolled
