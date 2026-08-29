"""Shared ``group_by`` machinery.

One code path, three query shapes — ``group_by`` in {"lob", "tool", "lob_tool"}
is a dimension selector, never a branch in engine logic (brief §3).
"""
from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import Any

from .loader import GROUP_BY_DIMS, Session


class SliceKey(tuple):
    """A group_by key, e.g. ("insurance",) or ("insurance", "claude_code")."""

    __slots__ = ()

    def as_dict(self, dims: Sequence[str]) -> dict[str, str]:
        return {d: v for d, v in zip(dims, self)}


def validate_group_by(group_by: str) -> tuple[str, ...]:
    if group_by not in GROUP_BY_DIMS:
        raise ValueError(
            f"group_by must be one of {sorted(GROUP_BY_DIMS)}, got {group_by!r}"
        )
    return GROUP_BY_DIMS[group_by]


def slice_key(session: Session, dims: Sequence[str]) -> SliceKey:
    return SliceKey(getattr(session, d) for d in dims)


def filter_weeks(
    sessions: Iterable[Session],
    week_from: int | None = None,
    week_to: int | None = None,
) -> list[Session]:
    lo = week_from if week_from is not None else -10**9
    hi = week_to if week_to is not None else 10**9
    return [s for s in sessions if lo <= s.week <= hi]


def group(
    sessions: Iterable[Session], dims: Sequence[str]
) -> dict[SliceKey, list[Session]]:
    out: dict[SliceKey, list[Session]] = {}
    for s in sessions:
        out.setdefault(slice_key(s, dims), []).append(s)
    return out


def group_by_slice_week(
    sessions: Iterable[Session], dims: Sequence[str]
) -> dict[tuple[SliceKey, int], list[Session]]:
    out: dict[tuple[SliceKey, int], list[Session]] = {}
    for s in sessions:
        out.setdefault((slice_key(s, dims), s.week), []).append(s)
    return out


def contiguous_ranges(weeks: Iterable[int]) -> list[tuple[int, int]]:
    """[1,2,3,5,6] -> [(1,3),(5,6)]."""
    ws = sorted(set(weeks))
    if not ws:
        return []
    ranges: list[tuple[int, int]] = []
    start = prev = ws[0]
    for w in ws[1:]:
        if w == prev + 1:
            prev = w
            continue
        ranges.append((start, prev))
        start = prev = w
    ranges.append((start, prev))
    return ranges


def ranges_overlap(a: tuple[int, int], b: tuple[int, int]) -> bool:
    return a[0] <= b[1] and b[0] <= a[1]


def merge_range(a: tuple[int, int], b: tuple[int, int]) -> tuple[int, int]:
    return (min(a[0], b[0]), max(a[1], b[1]))


def safe_div(n: float, d: float, default: float = 0.0) -> float:
    return n / d if d else default


def key_payload(key: SliceKey, dims: Sequence[str]) -> dict[str, Any]:
    """Render a slice key as {"lob_id": ..., "tool_id": ...} for API output."""
    return dict(zip(dims, key))
