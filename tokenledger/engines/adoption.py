"""Adoption Engine (brief §3.2).

Per group_by slice and per week:
  * WAU + WoW growth rate
  * Activation rate (>=3 sessions in first 2 weeks of the user's cohort)
  * Sessions/user/week (engagement depth)
  * Retention (prior-week-active users still active this week)
  * Non-human session share  -- stubbed to 0.0 for this dataset (see note)
  * Seat utilization + wasted-seat $  -- tool-dimension slices only

Per slice, a ``funnel`` snapshot as of the last week in the range:
  Eligible >= Onboarded >= Activated >= Habitual >= Power user
Each stage is a strict subset of the previous, so the funnel is monotonically
non-increasing by construction.

Cohort note: the locked schema (brief §2) has no ``cohort_start_week`` field,
so "cohort" is taken as the first week a user is observed active *in that
slice*. This is the observable proxy for onboarding and is stable under the
deterministic generator. The funnel (like activation) is computed over the
user's full session history up to the snapshot week, not just the requested
window, so consecutive-week runs are not truncated by ``week_from``.
"""
from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from ..loader import Manifest, Session, load_manifest, load_sessions
from ..reference import WEEKS_PER_MONTH
from ..slicing import (
    SliceKey,
    filter_weeks,
    group as group_sessions,
    key_payload,
    safe_div,
    validate_group_by,
)

ACTIVATION_MIN_SESSIONS = 3
ACTIVATION_WINDOW_WEEKS = 2  # cohort week and the one after
HABITUAL_CONSECUTIVE_WEEKS = 4       # weekly-active run to count as habitual
POWER_USER_TOP_FRACTION = 0.10       # top decile of sessions/active-week in-slice


def _wau_by_week(sessions: Sequence[Session]) -> dict[int, set[str]]:
    out: dict[int, set[str]] = {}
    for s in sessions:
        out.setdefault(s.week, set()).add(s.user_id)
    return out


def _sessions_by_user_week(sessions: Sequence[Session]) -> dict[tuple[str, int], int]:
    out: dict[tuple[str, int], int] = {}
    for s in sessions:
        out[(s.user_id, s.week)] = out.get((s.user_id, s.week), 0) + 1
    return out


def _cohort_week(sessions: Sequence[Session]) -> dict[str, int]:
    out: dict[str, int] = {}
    for s in sessions:
        if s.user_id not in out or s.week < out[s.user_id]:
            out[s.user_id] = s.week
    return out


def _activation(
    slice_sessions: Sequence[Session],
) -> dict[int, dict[str, Any]]:
    """Activation rate keyed by cohort week."""
    cohort = _cohort_week(slice_sessions)
    sess_uw = _sessions_by_user_week(slice_sessions)

    per_cohort: dict[int, dict[str, Any]] = {}
    for user, c_week in cohort.items():
        window = range(c_week, c_week + ACTIVATION_WINDOW_WEEKS)
        n = sum(sess_uw.get((user, w), 0) for w in window)
        bucket = per_cohort.setdefault(c_week, {"onboarded": 0, "activated": 0})
        bucket["onboarded"] += 1
        if n >= ACTIVATION_MIN_SESSIONS:
            bucket["activated"] += 1

    for c_week, b in per_cohort.items():
        b["activation_rate"] = round(safe_div(b["activated"], b["onboarded"]), 4)
    return per_cohort


def _longest_active_run(active_weeks: set[int], up_to: int) -> int:
    """Longest run of consecutive weeks in [1, up_to] all present in active_weeks."""
    best = run = 0
    for w in range(1, up_to + 1):
        run = run + 1 if w in active_weeks else 0
        best = max(best, run)
    return best


def _funnel(
    slice_sessions: Sequence[Session],
    manifest: Manifest,
    dims: Sequence[str],
    key: SliceKey,
    as_of_week: int,
) -> dict[str, Any]:
    """Five-stage funnel snapshot: Eligible >= Onboarded >= Activated >= Habitual
    >= Power user. Each stage is a subset of the previous one."""
    cohort = _cohort_week(slice_sessions)
    sess_uw = _sessions_by_user_week(slice_sessions)

    # Eligible: the addressable roster for this slice (from manifest counts).
    if "lob_id" in dims:
        lob_id = key[dims.index("lob_id")]
        eligible = manifest.users_per_lob.get(lob_id, len({s.user_id for s in slice_sessions}))
    else:  # tool-only slice: every LOB that actually uses this tool
        lobs_using = {s.lob_id for s in slice_sessions}
        eligible = sum(manifest.users_per_lob.get(lob, 0) for lob in lobs_using) \
            or len({s.user_id for s in slice_sessions})

    onboarded = {u for u, cw in cohort.items() if cw <= as_of_week}

    activated: set[str] = set()
    active_weeks: dict[str, set[str]] = {}
    total_sessions: dict[str, int] = {}
    for u in onboarded:
        cw = cohort[u]
        window = range(cw, cw + ACTIVATION_WINDOW_WEEKS)
        if sum(sess_uw.get((u, w), 0) for w in window) >= ACTIVATION_MIN_SESSIONS:
            activated.add(u)
        weeks = {w for (uu, w), n in sess_uw.items() if uu == u and w <= as_of_week and n > 0}
        active_weeks[u] = weeks
        total_sessions[u] = sum(n for (uu, w), n in sess_uw.items() if uu == u and w <= as_of_week)

    habitual = {
        u for u in activated
        if _longest_active_run(active_weeks[u], as_of_week) >= HABITUAL_CONSECUTIVE_WEEKS
    }

    # Power user: top decile by sessions per active week, measured across the
    # slice's own onboarded population, then intersected with habitual.
    spw = {u: safe_div(total_sessions[u], len(active_weeks[u])) for u in onboarded if active_weeks[u]}
    power_user: set[str] = set()
    if spw:
        ranked = sorted(spw, key=spw.get, reverse=True)  # type: ignore[arg-type]
        k = max(1, round(len(ranked) * POWER_USER_TOP_FRACTION))
        cutoff = spw[ranked[k - 1]]
        top_decile = {u for u, v in spw.items() if v >= cutoff}
        power_user = top_decile & habitual

    return {
        "as_of_week": as_of_week,
        "eligible": eligible,
        "onboarded": len(onboarded),
        "activated": len(activated),
        "habitual": len(habitual),
        "power_user": len(power_user),
        "definitions": {
            "eligible": "addressable user roster for the slice (manifest counts)",
            "onboarded": ">=1 session in the slice by the snapshot week",
            "activated": f">={ACTIVATION_MIN_SESSIONS} sessions in the first "
                         f"{ACTIVATION_WINDOW_WEEKS} weeks of the user's cohort",
            "habitual": f"activated AND a run of >={HABITUAL_CONSECUTIVE_WEEKS} "
                        f"consecutive weekly-active weeks",
            "power_user": f"habitual AND in the top {POWER_USER_TOP_FRACTION:.0%} of "
                          f"sessions-per-active-week within the slice",
        },
    }


def _seat_info(
    manifest: Manifest, dims: Sequence[str], key: SliceKey
) -> tuple[str | None, int | None, float | None]:
    """Return (tool_id, licensed_seats, cost_per_seat) for the slice or (None,..)."""
    if "tool_id" not in dims:
        return None, None, None
    tool_id = key[dims.index("tool_id")]
    cost_per_seat = manifest.cost_per_seat(tool_id)
    seats_per_lob = manifest.seats_per_lob.get(tool_id)
    if seats_per_lob is None:
        return tool_id, None, cost_per_seat
    if "lob_id" in dims:
        seats = seats_per_lob
    else:  # group_by=tool -> seats summed across every LOB
        seats = seats_per_lob * len(manifest.lobs)
    return tool_id, seats, cost_per_seat


def adoption(
    group_by: str,
    week_from: int | None = None,
    week_to: int | None = None,
    sessions: Sequence[Session] | None = None,
    manifest: Manifest | None = None,
) -> dict[str, Any]:
    dims = validate_group_by(group_by)
    manifest = manifest or load_manifest()
    all_rows = sessions if sessions is not None else load_sessions()
    # Activation needs the full cohort window; compute cohorts on unfiltered
    # data, then report weeks within the requested range.
    groups_all = group_sessions(all_rows, dims)
    report_lo = week_from if week_from is not None else min((s.week for s in all_rows), default=1)
    report_hi = week_to if week_to is not None else max((s.week for s in all_rows), default=1)

    out_slices = []
    for key, slice_sessions in sorted(groups_all.items()):
        wau = _wau_by_week(slice_sessions)
        sess_uw = _sessions_by_user_week(slice_sessions)
        activation = _activation(slice_sessions)
        tool_id, seats, cost_per_seat = _seat_info(manifest, dims, key)

        weeks_out = []
        for week in range(report_lo, report_hi + 1):
            active = wau.get(week, set())
            prev = wau.get(week - 1, set())
            wau_n = len(active)
            prev_n = len(prev)

            retained = len(active & prev)
            week_row: dict[str, Any] = {
                "week": week,
                "wau": wau_n,
                "wow_growth_rate": round(safe_div(wau_n - prev_n, prev_n), 4) if prev_n else None,
                "sessions_per_user": round(
                    safe_div(sum(sess_uw.get((u, week), 0) for u in active), wau_n), 4
                ),
                "retention_rate": round(safe_div(retained, prev_n), 4) if prev_n else None,
                "activation_rate": activation.get(week, {}).get("activation_rate"),
                "activation_cohort_size": activation.get(week, {}).get("onboarded"),
                # v1 dataset is 100% human-initiated; do not fabricate
                # managed-agent-initiated sessions.
                "non_human_session_share": 0.0,
            }

            if tool_id is not None:
                if seats:
                    util = safe_div(wau_n, seats)
                    unused = max(0, seats - wau_n)
                    week_cost = (cost_per_seat / WEEKS_PER_MONTH) if cost_per_seat is not None else None
                    week_row["seat_utilization"] = {
                        "licensed_seats": seats,
                        "active_users": wau_n,
                        "utilization_pct": round(util * 100, 2),
                        "unused_seats": unused,
                        # cost_per_seat in the registry is $/seat/MONTH; this
                        # block is per-week, so the wasted figure is weekly.
                        "cost_per_seat_month_usd": cost_per_seat,
                        "cost_per_seat_week_usd": round(week_cost, 4) if week_cost is not None else None,
                        "wasted_seat_cost_week_usd": round(unused * week_cost, 2)
                        if week_cost is not None else None,
                    }
                else:
                    week_row["seat_utilization"] = {
                        "licensed_seats": None,
                        "active_users": wau_n,
                        "note": "no licensed seat count declared for this tool",
                        "cost_per_seat_month_usd": cost_per_seat,
                    }

            weeks_out.append(week_row)

        out_slices.append({
            **key_payload(key, dims),
            "funnel": _funnel(slice_sessions, manifest, dims, key, report_hi),
            "activation_by_cohort_week": {
                str(w): activation[w] for w in sorted(activation)
            },
            "weeks": weeks_out,
        })

    return {
        "engine": "adoption",
        "group_by": group_by,
        "week_from": week_from,
        "week_to": week_to,
        "slices": out_slices,
    }
