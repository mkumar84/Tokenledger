"""Recommendation Engine (brief §3.4).

Joins Adoption Engine + Anti-Pattern Detector output into ONE ranked list.
Every recommendation carries:
  * dollar impact and/or adoption impact (labelled)
  * an unambiguous owner (a LOB owner or a Tool owner from the registry)
  * a quadrant classification where a slice is involved
  * a one-line remediation (not just a diagnosis)

Quality gates before emit:
  * materiality  -- > $50/week impact OR > 10% adoption-metric move
  * no-regression -- never recommend a cheaper model for a slice where outcome
    rate would plausibly drop (checked against outcome rates on the cheaper
    tier elsewhere in the dataset)
"""
from __future__ import annotations

from collections.abc import Sequence
from statistics import fmean
from typing import Any

from ..loader import Manifest, Session, load_manifest, load_sessions
from ..reference import CHEAPEST_MODEL, FRONTIER_MODELS
from ..slicing import filter_weeks, safe_div
from .adoption import adoption
from .antipattern import detect
from .quadrant import classify

# Materiality: the brief's example default is >$50/week; Northbridge's synthetic
# token spend runs ~1-2 orders of magnitude below a real fleet, so the tactical
# floor is calibrated down. Systemic recommendations (cross-LOB platform
# rollups, licence governance, tool deprecation/consolidation) bypass the
# dollar floor — they are cheap, one-time fixes whose value is structural, not
# weekly-run-rate. Override via TOKENLEDGER_MATERIALITY_USD_PER_WEEK.
import os as _os

MATERIALITY_USD_PER_WEEK = float(_os.environ.get("TOKENLEDGER_MATERIALITY_USD_PER_WEEK", 8.0))
MATERIALITY_ADOPTION_MOVE = 0.10
SEAT_UTIL_RECO_CEIL = 60.0
REGRESSION_OUTCOME_MULT = 1.2

# sources whose value is structural — never gated on weekly dollar run-rate
SYSTEMIC_SOURCES = {
    "anti_pattern.tool_level_rollup",
    "adoption.seat_utilization",
    "governance.tool_shape_similarity",
    "quadrant",  # enablement / deprecation calls are structural, not run-rate
}

# remediation lines per anti-pattern category
REMEDIATION = {
    "cache_expiration_churn": "Extend prompt-cache TTL to the 1-hour default and pin stable context blocks.",
    "zero_outcome_sessions": "Add pre-flight routing/guardrails so no-signal requests never reach a paid model.",
    "context_window_bloat": "Cap retrieved context and prune the system prompt to the fleet baseline.",
    "suboptimal_model_routing": "Route short, low-output sessions to the efficient tier; keep frontier for complex work.",
    "reasoning_effort_mismatch": "Default reasoning_effort to low/medium; escalate only on long or high-token sessions.",
    "chatty_tool_use": "Batch tool calls per turn and tighten the tool-selection prompt.",
}

MODEL_DOWNGRADE_CATEGORIES = {"suboptimal_model_routing", "reasoning_effort_mismatch"}


def _weeks_span(week_from: int | None, week_to: int | None, sessions: Sequence[Session]) -> int:
    lo = week_from if week_from is not None else min(s.week for s in sessions)
    hi = week_to if week_to is not None else max(s.week for s in sessions)
    return max(1, hi - lo + 1)


def _regression_risk(sessions: Sequence[Session]) -> dict[str, Any]:
    """Would moving work to the cheaper tier plausibly hurt outcomes?

    Compare zero-outcome rate on the cheapest tier vs frontier tiers across the
    whole dataset. If the cheap tier is materially worse, downgrade recs are
    unsafe.
    """
    cheap = [s for s in sessions if s.model == CHEAPEST_MODEL]
    frontier = [s for s in sessions if s.model in FRONTIER_MODELS]
    cheap_zero = safe_div(sum(s.is_zero_outcome for s in cheap), len(cheap))
    frontier_zero = safe_div(sum(s.is_zero_outcome for s in frontier), len(frontier))
    unsafe = bool(cheap and frontier and cheap_zero > frontier_zero * REGRESSION_OUTCOME_MULT)
    return {
        "cheap_tier_zero_outcome_rate": round(cheap_zero, 3),
        "frontier_tier_zero_outcome_rate": round(frontier_zero, 3),
        "downgrade_unsafe": unsafe,
    }


def _priority_score(dollar_per_week: float | None, adoption_move: float | None) -> float:
    d = dollar_per_week or 0.0
    a = (adoption_move or 0.0) * 1000.0  # 10% move ~ $100/wk-equivalent weight
    return d + a


def recommend(
    week_from: int | None = None,
    week_to: int | None = None,
    sessions: Sequence[Session] | None = None,
    manifest: Manifest | None = None,
) -> dict[str, Any]:
    manifest = manifest or load_manifest()
    all_rows = sessions if sessions is not None else load_sessions()
    scoped = filter_weeks(all_rows, week_from, week_to)
    if not scoped:
        return {"engine": "recommendation", "recommendations": [], "suppressed": []}

    span = _weeks_span(week_from, week_to, scoped)
    lo = week_from if week_from is not None else min(s.week for s in scoped)
    hi = week_to if week_to is not None else max(s.week for s in scoped)

    ap = detect("tool", week_from, week_to, sessions=all_rows, manifest=manifest)
    ad_tool = adoption("tool", week_from, week_to, sessions=all_rows, manifest=manifest)
    regression = _regression_risk(all_rows)

    candidates: list[dict[str, Any]] = []

    # --- 1. tool-level anti-pattern rollups ---------------------------
    for tool_id, findings in ap["tool_level_findings"].items():
        for f in findings:
            if f.get("scope") == "tool_level_rollup":
                candidates.append(_from_rollup(f, span, manifest, regression))
            else:
                candidates.append(_from_lob_finding(f, span, manifest, regression, all_rows))

    # --- 2. seat utilization -------------------------------------
    for sl in ad_tool["slices"]:
        tool_id = sl["tool_id"]
        weeks = [w for w in sl["weeks"] if "seat_utilization" in w]
        utils = [w["seat_utilization"] for w in weeks if w["seat_utilization"].get("utilization_pct") is not None]
        if not utils:
            continue
        avg_util = fmean(u["utilization_pct"] for u in utils)
        if avg_util >= SEAT_UTIL_RECO_CEIL:
            continue
        wasted = fmean(u["wasted_seat_cost_usd"] for u in utils if u["wasted_seat_cost_usd"] is not None) \
            if any(u["wasted_seat_cost_usd"] is not None for u in utils) else None
        candidates.append({
            "title": f"Consolidate / renegotiate {tool_id} licenses at renewal",
            "source": "adoption.seat_utilization",
            "lob_id": None,
            "tool_id": tool_id,
            "owner": manifest.tool_owner(tool_id),
            "impact_type": "dollar",
            "dollar_impact_usd": round(wasted, 2) if wasted is not None else None,
            "dollar_impact_per_week_usd": round(wasted, 2) if wasted is not None else None,
            "adoption_impact": None,
            "quadrant": None,
            "remediation": f"Right-size to ~{avg_util:.0f}% utilised seat count or fold into an "
                           f"existing tool; revisit before the next renewal.",
            "evidence": {"avg_seat_utilization_pct": round(avg_util, 1)},
        })

    # --- 3. quadrant-driven adoption recs (per LOB primary agent) -----
    for lob, agents in manifest.lob_managed_agents.items():
        if not agents:
            continue
        agent = agents[0]
        q = classify(lob, agent, lo, hi, sessions=all_rows)
        if q["quadrant"] is None:
            continue
        slice_rows = [s for s in scoped if s.lob_id == lob and s.tool_id == agent]
        slice_spend = sum(s.cost_usd for s in slice_rows)
        if q["quadrant"] == "Stalled + Efficient":
            candidates.append({
                "title": f"Enablement push for {agent} in {lob}",
                "source": "quadrant",
                "lob_id": lob, "tool_id": agent,
                "owner": manifest.lob_owner(lob),
                "impact_type": "adoption",
                "dollar_impact_usd": None,
                "dollar_impact_per_week_usd": None,
                "adoption_impact": "Close activation/adoption gap — usage is flat but spend is healthy.",
                "adoption_move_estimate": 0.25,
                "quadrant": q["quadrant"],
                "remediation": "Run targeted onboarding + template library for this team; this is an "
                               "enablement gap, not a cost problem.",
                "evidence": q["signals"],
            })
        elif q["quadrant"] == "Stalled + Wasteful":
            candidates.append({
                "title": f"Deprecation review: {agent} in {lob}",
                "source": "quadrant",
                "lob_id": lob, "tool_id": agent,
                "owner": manifest.lob_owner(lob),
                "impact_type": "both",
                "dollar_impact_usd": round(slice_spend, 2),
                "dollar_impact_per_week_usd": round(slice_spend / span, 2),
                "adoption_impact": "Low, flat adoption — few users would be disrupted by retirement.",
                "adoption_move_estimate": 0.0,
                "quadrant": q["quadrant"],
                "remediation": "Migrate the handful of active users to the reference agent and retire "
                               "this one; it is both unused and expensive per session.",
                "evidence": q["signals"],
            })

    # --- 4. tool consolidation candidates (near-identical shape, one LOB)
    candidates.extend(_consolidation_candidates(scoped, span, manifest))

    # --- quality gates -------------------------------------------
    kept: list[dict[str, Any]] = []
    suppressed: list[dict[str, Any]] = []
    for c in candidates:
        reason = _gate(c, regression)
        if reason:
            c = dict(c, suppressed_reason=reason)
            suppressed.append(c)
        else:
            kept.append(c)

    kept.sort(
        key=lambda c: _priority_score(
            c.get("dollar_impact_per_week_usd"), c.get("adoption_move_estimate")
        ),
        reverse=True,
    )
    for i, c in enumerate(kept, 1):
        c["rank"] = i

    return {
        "engine": "recommendation",
        "week_from": week_from,
        "week_to": week_to,
        "materiality": {
            "min_dollar_per_week_usd": MATERIALITY_USD_PER_WEEK,
            "min_adoption_move": MATERIALITY_ADOPTION_MOVE,
        },
        "no_regression_check": regression,
        "recommendations": kept,
        "suppressed": suppressed,
    }


def _from_rollup(f: dict[str, Any], span: int, manifest: Manifest, regression: dict) -> dict[str, Any]:
    cat = f["category"]
    dollar = f.get("dollar_impact_usd")
    fspan = max(1, f["week_to"] - f["week_from"] + 1)
    return {
        "title": f"Platform fix: {cat.replace('_', ' ')} on {f['tool_id']} across {f['lob_count']} LOBs",
        "source": "anti_pattern.tool_level_rollup",
        "lob_id": None,
        "tool_id": f["tool_id"],
        "lobs": f["lobs"],
        "owner": f["owner"] or manifest.tool_owner(f["tool_id"]),
        "impact_type": "dollar",
        "dollar_impact_usd": dollar,
        "dollar_impact_per_week_usd": round(dollar / fspan, 2) if dollar is not None else None,
        "adoption_impact": None,
        "quadrant": None,
        "remediation": REMEDIATION.get(cat, "Investigate and remediate at the platform level."),
        "evidence": {"week_from": f["week_from"], "week_to": f["week_to"],
                     "lobs": f["lobs"], "category": cat},
    }


def _from_lob_finding(
    f: dict[str, Any], span: int, manifest: Manifest, regression: dict, all_rows: Sequence[Session]
) -> dict[str, Any]:
    cat = f["category"]
    dollar = f.get("dollar_impact_usd")
    lob = f["lob_id"]
    tool = f["tool_id"]
    fspan = max(1, f["week_to"] - f["week_from"] + 1)
    q = classify(lob, tool, f["week_from"], f["week_to"], sessions=all_rows)
    return {
        "title": f"{cat.replace('_', ' ').capitalize()} — {tool} in {lob} (weeks {f['week_from']}-{f['week_to']})",
        "source": "anti_pattern.lob_level",
        "lob_id": lob,
        "tool_id": tool,
        "owner": manifest.tool_owner(tool) if manifest.tool_registry.get(tool, {}).get("category") == "managed_agent"
        else manifest.lob_owner(lob),
        "impact_type": "dollar",
        "dollar_impact_usd": dollar,
        "dollar_impact_per_week_usd": round(dollar / fspan, 2) if dollar is not None else None,
        "adoption_impact": None,
        "quadrant": q["quadrant"],
        "remediation": REMEDIATION.get(cat, "Investigate and remediate."),
        "category": cat,
        "evidence": q["signals"],
    }


CONSOLIDATION_RELDIFF_CEIL = 0.10   # mean per-axis relative gap
CONSOLIDATION_MIN_SESSIONS = 25
CONSOLIDATION_SETTLE_WEEK = 9       # compare on the settled window only


def _consolidation_candidates(
    scoped: Sequence[Session], span: int, manifest: Manifest
) -> list[dict[str, Any]]:
    """Two same-category tools with a near-identical usage shape *in one LOB*.

    Compared on the settled window (week >= CONSOLIDATION_SETTLE_WEEK when the
    range reaches it) so a transient arc — e.g. the claude_code cache issue —
    doesn't hide an otherwise-identical shape.
    """
    cat_tools: dict[str, list[str]] = {}
    for t, meta in manifest.tool_registry.items():
        if meta["category"] == "interactive_dev_harness":
            cat_tools.setdefault(meta["category"], []).append(t)

    max_week = max((s.week for s in scoped), default=0)
    settle = CONSOLIDATION_SETTLE_WEEK if max_week >= CONSOLIDATION_SETTLE_WEEK + 1 else 0
    window = [s for s in scoped if s.week >= settle]
    window_weeks = len({s.week for s in window}) or 1

    by_lob_tool: dict[tuple[str, str], list[Session]] = {}
    for s in window:
        by_lob_tool.setdefault((s.lob_id, s.tool_id), []).append(s)

    out: list[dict[str, Any]] = []
    for lob in manifest.lobs:
        for tools in cat_tools.values():
            present = [(t, by_lob_tool[(lob, t)]) for t in tools if (lob, t) in by_lob_tool]
            for i in range(len(present)):
                for j in range(i + 1, len(present)):
                    (ta, ra), (tb, rb) = present[i], present[j]
                    if len(ra) < CONSOLIDATION_MIN_SESSIONS or len(rb) < CONSOLIDATION_MIN_SESSIONS:
                        continue
                    rd = _shape_reldiff(ra, rb)
                    if rd > CONSOLIDATION_RELDIFF_CEIL:
                        continue
                    smaller_tool, smaller_rows = (ta, ra) if len(ra) <= len(rb) else (tb, rb)
                    weekly_saving = sum(s.cost_usd for s in smaller_rows) / window_weeks
                    seat = manifest.cost_per_seat(smaller_tool)
                    out.append({
                        "title": f"Localized consolidation: {ta} + {tb} in {lob}",
                        "source": "governance.tool_shape_similarity",
                        "lob_id": lob,
                        "tool_id": smaller_tool,
                        "owner": manifest.tool_owner(smaller_tool),
                        "impact_type": "dollar",
                        "dollar_impact_usd": round(weekly_saving * span, 2),
                        "dollar_impact_per_week_usd": round(weekly_saving, 2),
                        "adoption_impact": None,
                        "quadrant": None,
                        "remediation": f"Usage shape is near-identical in {lob} only — standardise this "
                                       f"team on one tool and drop {smaller_tool}"
                                       + (f" (${seat}/seat/mo)." if seat else "."),
                        "evidence": {"mean_axis_relative_diff": round(rd, 4),
                                     "compared_from_week": settle or 1},
                    })
    return out


def _shape_reldiff(a: Sequence[Session], b: Sequence[Session]) -> float:
    va, vb = _shape_vector(a), _shape_vector(b)
    return fmean(abs(x - y) / max(abs(x), abs(y), 1e-9) for x, y in zip(va, vb))


def _shape_vector(rows: Sequence[Session]) -> list[float]:
    n = len(rows)
    users = len({s.user_id for s in rows})
    return [
        safe_div(n, users),
        fmean(s.turn_count for s in rows),
        fmean(s.requests_per_turn for s in rows),
        fmean(s.tokens_in for s in rows) / 1000,
        fmean(s.tokens_out for s in rows) / 1000,
        fmean(s.cache_hit_rate for s in rows),
    ]


def _gate(c: dict[str, Any], regression: dict[str, Any]) -> str | None:
    # no-regression: block model-downgrade recs if the cheap tier is worse
    if c.get("category") in MODEL_DOWNGRADE_CATEGORIES and regression["downgrade_unsafe"]:
        return ("no-regression: cheaper model tier shows a higher zero-outcome rate "
                f"({regression['cheap_tier_zero_outcome_rate']:.0%} vs "
                f"{regression['frontier_tier_zero_outcome_rate']:.0%})")
    # systemic recs (platform rollups, licence governance, consolidation) are
    # structural one-time fixes — not gated on weekly dollar run-rate
    if c.get("source") in SYSTEMIC_SOURCES:
        return None
    # materiality
    dpw = c.get("dollar_impact_per_week_usd")
    move = c.get("adoption_move_estimate")
    if (dpw is None or dpw < MATERIALITY_USD_PER_WEEK) and (move is None or move < MATERIALITY_ADOPTION_MOVE):
        return (f"below materiality threshold (${dpw or 0:.2f}/wk, "
                f"{(move or 0) * 100:.0f}% adoption move)")
    return None
