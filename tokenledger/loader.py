"""Load sessions + manifest, with a small typed view over each.

Cached at module level so the API and the test-suite share one parse of the
~4.2k-line ``sessions.jsonl``.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any

from .config import MANIFEST_PATH, SESSIONS_PATH
from .reference import LOB_OWNERS_FALLBACK, MODEL_PRICING

# --- session schema (locked, brief §2) -------------------------------------

SESSION_FIELDS = (
    "session_id", "user_id", "team_id", "lob_id", "tool_id", "agent_id",
    "layer", "week", "turn_count", "requests_per_turn", "tokens_in",
    "tokens_out", "model", "reasoning_effort", "cache_hit_rate", "cost_usd",
    "outcome",
)

GROUP_BY_DIMS: dict[str, tuple[str, ...]] = {
    "lob": ("lob_id",),
    "tool": ("tool_id",),
    "lob_tool": ("lob_id", "tool_id"),
}

ZERO_OUTCOME = "none"


@dataclass(frozen=True)
class Session:
    session_id: str
    user_id: str
    team_id: str
    lob_id: str
    tool_id: str
    agent_id: str | None
    layer: str
    week: int
    turn_count: int
    requests_per_turn: int
    tokens_in: int
    tokens_out: int
    model: str
    reasoning_effort: str
    cache_hit_rate: float
    cost_usd: float
    outcome: str

    # --- derived cost split (see reference.MODEL_PRICING flag) ------------
    @property
    def output_cost_usd(self) -> float:
        price = MODEL_PRICING.get(self.model, {"output": 0.0})["output"]
        return round((self.tokens_out / 1000) * price, 6)

    @property
    def input_cost_usd(self) -> float:
        # residual, so input + output == cost_usd exactly
        return round(self.cost_usd - self.output_cost_usd, 6)

    @property
    def tokens_total(self) -> int:
        return self.tokens_in + self.tokens_out

    @property
    def requests(self) -> int:
        return self.turn_count * self.requests_per_turn

    @property
    def is_zero_outcome(self) -> bool:
        return self.outcome == ZERO_OUTCOME


@dataclass
class Manifest:
    raw: dict[str, Any]
    tool_registry: dict[str, dict[str, Any]] = field(default_factory=dict)
    lobs: list[str] = field(default_factory=list)
    users_per_lob: dict[str, int] = field(default_factory=dict)
    lob_managed_agents: dict[str, list[str]] = field(default_factory=dict)
    planted_arcs: list[dict[str, Any]] = field(default_factory=list)
    weeks: tuple[int, int] = (1, 12)

    # tool_id -> seats licensed per LOB (only where declared)
    seats_per_lob: dict[str, int] = field(default_factory=dict)
    lob_owners: dict[str, str] = field(default_factory=dict)

    def tool_owner(self, tool_id: str) -> str | None:
        return self.tool_registry.get(tool_id, {}).get("owner")

    def cost_per_seat(self, tool_id: str) -> float | None:
        return self.tool_registry.get(tool_id, {}).get("cost_per_seat")

    def lob_owner(self, lob_id: str) -> str:
        return self.lob_owners.get(lob_id) or LOB_OWNERS_FALLBACK.get(lob_id, f"{lob_id} owner")

    @property
    def week_list(self) -> list[int]:
        return list(range(self.weeks[0], self.weeks[1] + 1))


@lru_cache(maxsize=1)
def load_manifest() -> Manifest:
    raw = json.loads(MANIFEST_PATH.read_text())
    m = Manifest(
        raw=raw,
        tool_registry=raw.get("tool_registry", {}),
        lobs=raw.get("lobs", []),
        users_per_lob=raw.get("users_per_lob", {}),
        lob_managed_agents=raw.get("lob_managed_agents", {}),
        planted_arcs=raw.get("planted_arcs", []),
        weeks=tuple(raw.get("simulated_weeks", [1, 12])),  # type: ignore[arg-type]
    )
    # seat counts: any tool that declares `seats_per_lob` in the registry gets
    # seat-utilization treatment — no tool is special-cased by name. Planted
    # arcs are a fallback for older manifests that only carried it there.
    for tool_id, meta in m.tool_registry.items():
        if meta.get("seats_per_lob") is not None:
            m.seats_per_lob[tool_id] = meta["seats_per_lob"]
    for arc in m.planted_arcs:
        tool = arc.get("tool_or_agent")
        if tool and "seats_per_lob" in arc:
            m.seats_per_lob.setdefault(tool, arc["seats_per_lob"])
    # LOB owners: owning managed agent's owner.
    for lob, agents in m.lob_managed_agents.items():
        if agents:
            owner = m.tool_registry.get(agents[0], {}).get("owner")
            if owner:
                m.lob_owners[lob] = owner
    return m


@lru_cache(maxsize=1)
def load_sessions() -> list[Session]:
    out: list[Session] = []
    with SESSIONS_PATH.open() as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            d = json.loads(line)
            out.append(Session(**{k: d[k] for k in SESSION_FIELDS}))
    return out


def reset_caches() -> None:
    load_manifest.cache_clear()
    load_sessions.cache_clear()
