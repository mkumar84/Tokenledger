"""Adoption Engine (brief §3.2).

Per group_by slice and per week:
  * WAU + WoW growth rate
  * Activation rate (>=3 sessions in first 2 weeks of the user's cohort)
  * Sessions/user/week (engagement depth)
  * Retention (prior-week-active users still active this week)
  * Non-human session share  -- stubbed to 0.0 for this dataset (see note)
  * Seat utilization + wasted-seat $  -- tool-dimension slices only

Cohort note: the locked schema (brief §2) has no ``cohort_start_week`` field,
so "cohort" is taken as the first week a user is observed active *in that
slice*. This is the observable proxy for onboarding and is stable under the
deterministic generator.
"""
from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from ..loader import Manifest, Session, load_manifest, load_sessions
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
                    week_row["seat_utilization"] = {
                        "licensed_seats": seats,
                        "active_users": wau_n,
                        "utilization_pct": round(util * 100, 2),
                        "unused_seats": unused,
                        "cost_per_seat_usd": cost_per_seat,
                        "wasted_seat_cost_usd": round(unused * cost_per_seat, 2)
                        if cost_per_seat is not None else None,
                    }
                else:
                    week_row["seat_utilization"] = {
                        "licensed_seats": None,
                        "active_users": wau_n,
                        "note": "no licensed seat count declared for this tool",
                        "cost_per_seat_usd": cost_per_seat,
                    }

            weeks_out.append(week_row)

        out_slices.append({
            **key_payload(key, dims),
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
