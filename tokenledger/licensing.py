"""Seat-license spend — the additive, non-consumption cost component (Patch 5).

The six-term Cost Equation is purely consumption: ``users x sessions/user x
turns/session x requests/turn x tokens/request x price/token``. It structurally
cannot represent a flat recurring seat-license fee.

Seat-licensed tools are those with ``seats_per_lob`` in ``tool_registry``
(``cursor``: 20/LOB @ $40/seat/mo, ``saas_mcp_assist``: 25/LOB @ $60/seat/mo).
``cost_per_seat`` is dollars per seat per **month**; weekly figures use
``cost_per_seat / WEEKS_PER_MONTH``.

License spend for a (tool, LOB, week) = ``seats_per_lob x cost_per_seat / WEEKS_PER_MONTH``.
It is **additive** to the consumption total, never folded into the multiplicative
equation, and does not decompose (it is ``seats x rate``, full stop).
"""
from __future__ import annotations

from typing import Any

from .loader import Manifest
from .reference import WEEKS_PER_MONTH


def _window_weeks(manifest: Manifest, week_from: int | None, week_to: int | None) -> int:
    lo = week_from if week_from is not None else manifest.weeks[0]
    hi = week_to if week_to is not None else manifest.weeks[1]
    return max(0, hi - lo + 1)


def license_spend_detail(
    manifest: Manifest, week_from: int | None, week_to: int | None
) -> list[dict[str, Any]]:
    """Per seat-licensed tool: seats, monthly/weekly rate, and window spend."""
    n_weeks = _window_weeks(manifest, week_from, week_to)
    n_lobs = len(manifest.lobs) or 4
    out: list[dict[str, Any]] = []
    for tool_id, seats_per_lob in sorted(manifest.seats_per_lob.items()):
        month = manifest.cost_per_seat(tool_id)
        if month is None:
            continue
        seats_total = seats_per_lob * n_lobs
        weekly_rate = month / WEEKS_PER_MONTH
        spend = seats_total * weekly_rate * n_weeks
        out.append({
            "tool_id": tool_id,
            "seats_per_lob": seats_per_lob,
            "lobs": n_lobs,
            "seats_total": seats_total,
            "cost_per_seat_month_usd": month,
            "cost_per_seat_week_usd": round(weekly_rate, 4),
            "weeks": n_weeks,
            "license_spend_usd": round(spend, 2),
            "license_spend_per_lob_usd": round(spend / n_lobs, 2) if n_lobs else 0.0,
        })
    return out


def fleet_license_spend_usd(
    manifest: Manifest, week_from: int | None, week_to: int | None
) -> float:
    return round(
        sum(d["license_spend_usd"] for d in license_spend_detail(manifest, week_from, week_to)),
        2,
    )


def slice_license_spend_usd(
    manifest: Manifest,
    dims: tuple[str, ...],
    key: tuple[str, ...],
    week_from: int | None,
    week_to: int | None,
) -> float:
    """License spend attributable to one group_by slice.

    - grouping includes ``tool_id``: only that tool contributes (0 if it is not
      seat-licensed); seats = ``seats_per_lob`` (with a LOB in the key) or
      ``seats_per_lob x lobs`` (tool only).
    - grouping is ``lob`` only: every seat-licensed tool contributes its
      per-LOB seat block for that one LOB.
    """
    n_weeks = _window_weeks(manifest, week_from, week_to)
    n_lobs = len(manifest.lobs) or 4
    kd = dict(zip(dims, key))
    total = 0.0
    for tool_id, seats_per_lob in manifest.seats_per_lob.items():
        month = manifest.cost_per_seat(tool_id)
        if month is None:
            continue
        if "tool_id" in kd and kd["tool_id"] != tool_id:
            continue
        seats = seats_per_lob if "lob_id" in kd else seats_per_lob * n_lobs
        total += seats * (month / WEEKS_PER_MONTH) * n_weeks
    return round(total, 4)
