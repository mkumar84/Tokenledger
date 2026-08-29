"""Reference / lookup data — not derived from ``sessions.jsonl``.

The tool registry, LOB roster and seat counts all come from ``manifest.json``
(loaded in :mod:`tokenledger.loader`). This module holds the two pieces of
reference data that live *outside* the manifest:

1. ``MODEL_PRICING`` — fictional per-1K-token list prices by model tier.

   FLAG BACK TO SPEC OWNER: this table is duplicated from
   ``generate_sessions.py`` (§1 of the generator). ``sessions.jsonl`` carries
   ``model`` and ``cost_usd`` but not the input/output price split, and the
   Cost Equation Engine's driver decomposition (§3.1) needs to separate input
   vs output spend. Options if this is unacceptable: (a) add ``price_in`` /
   ``price_out`` to the session schema, or (b) publish ``MODEL_PRICING`` in
   ``manifest.json``. Until then we mirror the generator's constants verbatim
   and treat output cost as exact (``tokens_out/1000 * price_out``), input cost
   as the residual (``cost_usd - output_cost``) so per-session totals always
   reconcile to ``cost_usd``.

2. ``LOB_OWNERS`` — accountable owner per line of business, so the
   Recommendation Engine can always name an owner (§3.4). Derived from the
   manifest's ``lob_managed_agents`` → owning agent's ``owner`` at load time;
   the dict here is only the fallback if that lookup is unavailable.
"""
from __future__ import annotations

# Mirrors generate_sessions.py MODEL_PRICING (fictional, per 1K tokens).
MODEL_PRICING: dict[str, dict[str, float]] = {
    "frontier-large": {"input": 0.015, "output": 0.075},
    "frontier-medium": {"input": 0.003, "output": 0.015},
    "efficient-small": {"input": 0.0005, "output": 0.0025},
}

# Model tiers considered "frontier" for suboptimal-routing detection (§3.3).
FRONTIER_MODELS = frozenset({"frontier-large", "frontier-medium"})
FRONTIER_TOP_MODEL = "frontier-large"
CHEAPEST_MODEL = "efficient-small"

# Fallback LOB owners (the loader prefers manifest-derived owners).
LOB_OWNERS_FALLBACK: dict[str, str] = {
    "insurance": "Insurance AI Lead",
    "retail_banking": "Retail Banking AI Lead",
    "wealth_management": "Wealth Management AI Lead",
    "commercial_lending": "Commercial Lending AI Lead",
}

# The cache model used by the generator: effective billed input tokens =
# tokens_in * (1 - cache_hit_rate * CACHE_DISCOUNT). Used to estimate the
# dollar impact of a cache-hit-rate improvement.
CACHE_DISCOUNT = 0.9
