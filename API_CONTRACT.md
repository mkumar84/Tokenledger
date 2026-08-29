# TokenLedger API Contract (locked — Phase 1)

Authoritative reference for the Lovable frontend build. **This document is
generated against the running FastAPI app** (commit `ca8930f`), not from
memory — where it disagrees with an earlier hand-written draft, this document
wins. Re-verify against `GET /docs` (OpenAPI) after any backend change.

- Base: the deployed Railway URL, or `http://localhost:8000` locally.
- All endpoints are **GET**, read-only, no auth, synthetic data.
- Interactive docs: `/docs`. Machine-readable schema: `/openapi.json`.
- Data covers **weeks 1–12**, 4 LOBs, 8 tools, 4231 sessions (`GET /health`).

---

## ⚠️ Corrections vs. the reconstructed draft

The hand-written draft that circulated during review drifted in several places.
The real shapes:

| Draft said | Actual |
|---|---|
| every endpoint takes `group_by` (required) | `/recommendations` takes **no** `group_by`. `/quadrant` takes `lob_id`/`tool_id`, not `group_by`. Elsewhere `group_by` is **optional**, default `"lob"`. |
| `week_from`/`week_to` default to `1`/`12` | default to **absent**; the response echoes `null`. Behaviour is still "full history". |
| `/cost/drivers` takes `period_a`/`period_b` objects | takes four flat ints: `a_from`, `a_to`, `b_from`, `b_to` (all required). |
| `/cost` returns flat per-slice metrics | returns `slices[].weeks[]` — **always per week**, no range-aggregate mode. |
| `price_per_token_usd` | field is `price_per_token`. |
| drivers `total_delta_usd`, `adoption_usd`, `engagement_usd`, `input_tokens_usd`, `output_tokens_usd` | `delta_usd`, `adoption_users_usd`, `engagement_sessions_per_user_usd`, `input_token_workload_usd`, `output_token_workload_usd`. `residual_usd` may be `-0.0`. |
| `/adoption` returns flat metrics + `seat_info` | returns `slices[].weeks[]` per week; seat data is **`seat_utilization`**, per week, and has **no** `recent_trend_pct` / `trend_window_weeks` (those exist only in `/recommendations` evidence). |
| `wow_growth_pct` / `activation_rate_pct` / `retention_rate_pct` (percent 0–100) | `wow_growth_rate` / `activation_rate` / `retention_rate` — **fractions 0–1**, and `null` where undefined (week 1, or prior WAU = 0). |
| `seat_info: null` for non-seat tools | `seat_utilization` is still an object: `{"licensed_seats": null, "active_users": N, "note": "...", "cost_per_seat_usd": null}`. Test `licensed_seats !== null`, not `seat_utilization !== null`. |
| `/anti-patterns` returns `findings: [...]` with `finding_id` | returns `lob_level_findings` and `tool_level_findings` **objects keyed by id**, plus a separate `legitimate_variance_exclusions` list. No `finding_id`. |
| excluded findings appear in the findings list with `excluded: true` | excluded findings are **only** in `legitimate_variance_exclusions` — never in the findings objects. No client-side filtering needed. |
| rollup finding has `lobs_affected`, `remediation` | has `lobs`; remediation lives in `/recommendations`, not on the finding. |
| recs have `rec_id`, `owner_type`, `action` on every item | **no** `rec_id`, **no** `owner_type`. `action` is present **only** on `source: "adoption.seat_utilization"` recs. |
| `impact_type: "cost"` | `impact_type` is `"dollar"` \| `"adoption"` \| `"both"`. |
| `quadrant: "growing_wasteful"` | `quadrant: "Growing + Wasteful"` (title case, `" + "` separator) or `null`. |
| monitor rec `remediation: null` | `remediation` is always a non-empty string. |

---

## Common query parameters

| param | endpoints | type | required | default | notes |
|---|---|---|---|---|---|
| `group_by` | `/cost`, `/cost/drivers`, `/adoption` | `lob` \| `tool` \| `lob_tool` | no | `lob` | `/anti-patterns`: `lob` \| `tool` only (**`lob_tool` → 422**) |
| `week_from`, `week_to` | `/cost`, `/adoption`, `/anti-patterns`, `/recommendations` | int ≥ 1 | no | full history | inclusive; response echoes the value you passed (or `null`) |
| `a_from`, `a_to`, `b_from`, `b_to` | `/cost/drivers` | int ≥ 1 | **yes** | — | period A and period B week bounds, inclusive |
| `lob_id`, `tool_id` | `/quadrant` | string | ≥1 of the 2 | — | pass either or both; neither → 422 |
| `week_from`, `week_to` | `/quadrant` | int ≥ 1 | **yes** | — | |

- `group_by=lob` → each slice carries only `lob_id`. `group_by=tool` → only
  `tool_id`. `group_by=lob_tool` → both, **one row per (lob_id, tool_id) pair
  that has data** (not a full cross-join).
- Invalid `group_by` or an engine-level validation error → **422**
  `{"detail": "..."}`.
- Unknown query params are ignored (FastAPI). Passing `group_by` to
  `/recommendations` is accepted but has no effect.

---

## `GET /health`

```json
{
  "status": "ok",
  "version": "0.1.0",
  "sessions_loaded": 4231,
  "weeks": [1, 12],
  "lobs": ["insurance", "retail_banking", "wealth_management", "commercial_lending"],
  "tools": ["aml_alert_triage", "claims_triage_agent", "claude_code",
            "credit_memo_agent", "cursor", "fraud_ring_detector",
            "portfolio_summarizer", "saas_mcp_assist"]
}
```

`GET /` returns `{"service", "version", "endpoints": [...]}`.

---

## `GET /cost`

Six-term decomposition, **per slice, per week**.
`Total Spend = Users × Sessions/User × Turns/Session × Requests/Turn × Tokens/Request × Price/Token`

```jsonc
{
  "engine": "cost_equation",
  "group_by": "lob_tool",
  "week_from": 1,
  "week_to": 3,
  "equation": "Users x Sessions/User x Turns/Session x Requests/Turn x Tokens/Request x Price/Token",
  "slices": [
    {
      "lob_id": "insurance",          // present per group_by
      "tool_id": "claims_triage_agent",
      "weeks": [
        {
          "week": 1,
          "users": 3,
          "sessions_per_user": 4.333333,
          "turns_per_session": 4.846154,
          "requests_per_turn": 1.492063,
          "tokens_per_request": 603.085106,
          "price_per_token": 3.1681e-06,       // USD/token, blended
          "total_spend_usd": 0.1796,           // sum of cost_usd in the slice-week
          "reconstructed_spend_usd": 0.1796,   // product of the six factors
          "reconciles": true,                  // |reconstructed - total| within tolerance
          "sessions": 13,                      // supporting raw totals ↓
          "turns": 63,
          "requests": 94,
          "tokens": 56690,
          "lob_id": "insurance",               // slice key echoed onto each week row too
          "tool_id": "claims_triage_agent"
        }
        // ... one entry per week in [week_from, week_to]
      ]
    }
  ]
}
```

Frontend: `reconciles` is a quiet integrity check (small ✓ on hover), not a
headline metric. The six factors × each other = `total_spend_usd`.

---

## `GET /cost/drivers`

Two-period waterfall; the four drivers sum to `delta_usd` with **zero residual**.

Request: `/cost/drivers?group_by=lob_tool&a_from=1&a_to=4&b_from=9&b_to=12`

```jsonc
{
  "engine": "cost_equation.driver_decomposition",
  "group_by": "lob_tool",
  "period_a_weeks": [1, 4],
  "period_b_weeks": [9, 12],
  "slices": [
    {
      "lob_id": "insurance",
      "tool_id": "claims_triage_agent",
      "spend_a_usd": 0.8137,
      "spend_b_usd": 1.8883,
      "delta_usd": 1.0746,
      "drivers": {
        "adoption_users_usd": 0.8137,
        "engagement_sessions_per_user_usd": 0.3551,
        "input_token_workload_usd": -0.0487,
        "output_token_workload_usd": -0.0455
      },
      "residual_usd": 0.0        // always ~0 (may serialize as -0.0)
    }
  ]
}
```

Waterfall: `spend_a_usd` → +/− the four `drivers` → `spend_b_usd`.

---

## `GET /adoption`

Per slice: `activation_by_cohort_week` (once) + `weeks[]` (per week).

```jsonc
{
  "engine": "adoption",
  "group_by": "tool",
  "week_from": 1,
  "week_to": 12,
  "slices": [
    {
      "tool_id": "cursor",                    // only the grouped dim key(s)
      "activation_by_cohort_week": {
        "1": { "onboarded": 3, "activated": 2, "activation_rate": 0.6667 },
        "3": { "onboarded": 5, "activated": 0, "activation_rate": 0.0 }
        // key = the week a user cohort first appears in this slice
      },
      "weeks": [
        {
          "week": 12,
          "wau": 51,
          "wow_growth_rate": 0.0408,           // FRACTION, null on first week / prior WAU 0
          "sessions_per_user": 2.0784,
          "retention_rate": 0.5714,            // FRACTION, null on first week
          "activation_rate": 0.0,              // FRACTION; null for lob-only slices
          "activation_cohort_size": 1,         // null for lob-only slices
          "non_human_session_share": 0.0,      // STUB — always 0.0 in v1, do not build a varying UI
          "seat_utilization": {                // present only for group_by tool / lob_tool
            "licensed_seats": 80,              // 20/LOB × 4 for cursor at group_by=tool; 20 at lob_tool
            "active_users": 51,
            "utilization_pct": 63.75,          // PERCENT 0–100 here (unlike the rates above)
            "unused_seats": 29,
            "cost_per_seat_usd": 40,
            "wasted_seat_cost_usd": 1160
          }
        }
      ]
    }
  ]
}
```

**`seat_utilization` variants** (per week, on `group_by` = `tool` or `lob_tool`):

- seat-licensed tool (`cursor`, `saas_mcp_assist`): the full object above.
- any other tool (managed agents, `claude_code`):
  `{"licensed_seats": null, "active_users": N, "note": "no licensed seat count declared for this tool", "cost_per_seat_usd": null}`.
- `group_by=lob`: key is **absent** entirely.

Detect "has seat data" via `seat_utilization?.licensed_seats != null`.
There is **no trend field here** — recent-trend lives in `/recommendations`.

---

## `GET /anti-patterns`

`group_by` = `lob` | `tool` (not `lob_tool`).

```jsonc
{
  "engine": "anti_pattern_detector",
  "group_by": "tool",
  "week_from": 1,
  "week_to": 12,
  "categories": ["suboptimal_model_routing", "context_window_bloat",
    "cache_expiration_churn", "prompt_initialization_overhead", "chatty_tool_use",
    "reasoning_effort_mismatch", "zero_outcome_sessions"],
  "primary_view": "tool",

  "lob_level_findings": {           // object keyed by lob_id → array
    "insurance": [
      {
        "category": "cache_expiration_churn",
        "lob_id": "insurance",
        "tool_id": "claims_triage_agent",
        "week_from": 1,
        "week_to": 6,
        "severity": "low",           // "low" | "medium" | "high" (by $ impact)
        "dollar_impact_usd": 2.52,   // may be null for non-$ categories
        "metric": {
          "weeks_flagged": [1,2,3,4,5,6],
          "per_week": [ { "week": 1, "mean_cache_hit_rate": 0.24,
                          "fleet_baseline_cache_hit_rate": 0.509,
                          "dollar_impact_usd": 0.13 } /* ... */ ]
        },
        "detail": "Cache hit rate 19% vs 50% fleet baseline …",
        "rolled_up_into_tool_finding": false   // true → also inside a rollup below; hide from LOB view
      }
    ]
  },

  "tool_level_findings": {          // object keyed by tool_id → array
    "claude_code": [
      {
        "category": "cache_expiration_churn",
        "tool_id": "claude_code",
        "scope": "tool_level_rollup",       // ← the collapsed cross-LOB card
        "lobs": ["insurance", "retail_banking", "wealth_management"],
        "lob_count": 3,
        "total_lobs": 4,
        "week_from": 1,
        "week_to": 8,
        "owner": "Group Platform Eng",
        "dollar_impact_usd": 5.14,
        "severity": "low",
        "detail": "cache expiration churn present in 3 of 4 LOBs for claude_code …",
        "rolled_up_lob_findings": [ /* the per-LOB findings it absorbed */ ]
      }
      // NOTE: tool_level_findings[tool] ALSO contains that tool's own
      // non-rolled-up lob_level findings (scope absent) as passthrough.
    ]
  },

  "legitimate_variance_exclusions": [   // NOT waste — render in an "excluded / audit" section, if at all
    {
      "category": "context_window_bloat",
      "lob_id": "commercial_lending",
      "tool_id": "cursor",
      "week_from": 4, "week_to": 4,
      "weeks": [4],
      "detail": "… Outcome rate is normal — treated as legitimate workload variance, not waste."
    }
  ],

  "notes": {
    "prompt_initialization_overhead": "n/a at session level in this dataset — not scored.",
    "chatty_tool_use": "requests_per_turn has no planted variance in v1; rule active but expected silent."
  }
}
```

**Rollup rendering:** a `scope: "tool_level_rollup"` item is ONE card with a
`lobs` chip list — do not also render its `rolled_up_lob_findings` as separate
cards, and in the LOB view skip any finding with
`rolled_up_into_tool_finding: true`.

**Excluded findings:** already isolated in `legitimate_variance_exclusions`.
The findings objects never contain them and have no `excluded` flag — no
client-side filtering required.

---

## `GET /recommendations`

No `group_by`. Ranked, pre-sorted — **do not re-sort client-side.**

```jsonc
{
  "engine": "recommendation",
  "week_from": null,
  "week_to": null,
  "materiality": { "min_dollar_per_week_usd": 8.0, "min_adoption_move": 0.1 },
  "no_regression_check": {
    "cheap_tier_zero_outcome_rate": 0.13,
    "frontier_tier_zero_outcome_rate": 0.138,
    "downgrade_unsafe": false
  },
  "recommendations": [
    {
      "rank": 1,
      "source": "adoption.seat_utilization",   // ← see source list below
      "action": "consolidate",                 // ONLY on seat_utilization recs: "consolidate" | "monitor"
      "title": "Consolidate / renegotiate saas_mcp_assist licenses at renewal",
      "lob_id": null,
      "tool_id": "saas_mcp_assist",
      "owner": "Group Platform Eng",            // always a real name, never null
      "impact_type": "dollar",                  // "dollar" | "adoption" | "both"
      "dollar_impact_usd": 4510.0,
      "dollar_impact_per_week_usd": 4510.0,
      "adoption_impact": null,                  // string when impact_type involves adoption
      "quadrant": null,                         // "Growing + Wasteful" etc., or null
      "remediation": "Right-size to ~25% utilised seat count …",  // always a non-empty string
      "evidence": {                             // shape varies by source (see below)
        "avg_seat_utilization_pct": 24.8,
        "recent_trend_pct": 31.0,
        "trend_window_weeks": 3,
        "wasted_seat_cost_usd": 4510.0
      }
    }
  ],
  "suppressed": [
    { /* same fields, no "rank"; plus: */
      "suppressed_reason": "below materiality threshold ($0.64/wk, 0% adoption move)",
      "category": "cache_expiration_churn"      // present on anti-pattern-derived items
    }
  ]
}
```

### `source` values and their extra fields

| `source` | `action`? | extra fields | `evidence` shape |
|---|---|---|---|
| `adoption.seat_utilization` | `consolidate` \| `monitor` | — | `{avg_seat_utilization_pct, recent_trend_pct, trend_window_weeks, wasted_seat_cost_usd}` |
| `quadrant` | — | `adoption_move_estimate` (float), `quadrant` (string) | the quadrant `signals` object (see `/quadrant`) |
| `anti_pattern.tool_level_rollup` | — | `lobs` (array) | `{week_from, week_to, lobs, category}` |
| `anti_pattern.lob_level` | — | `category` | the quadrant `signals` for that slice |
| `governance.tool_shape_similarity` | — | — | `{mean_axis_relative_diff, compared_from_week}` |

### Ranking rule

`priority = (dollar_impact_per_week_usd or 0) + (adoption_move_estimate or 0) × 1000`,
descending. Effect: large-$ recs first, then adoption-move recs, then
`action: "monitor"` (score 0) last. `suppressed[]` is unranked.

### `action: "monitor"`

A **status note**, not a task: `impact_type: "adoption"`,
`dollar_impact_usd: null`, `dollar_impact_per_week_usd: null`. Render distinctly
(muted, "no action needed"), keep it at the bottom. It carries the same
`evidence` fields as a `consolidate` rec for context.

### Quality gates (already applied server-side)

- **Materiality** — tactical per-slice recs need `> $8/week` **or**
  `> 10%` adoption move; otherwise they move to `suppressed[]`. Systemic recs
  (rollups, seat governance, deprecation, consolidation) bypass the $ floor.
- **No-regression** — a model-downgrade rec is suppressed if the cheaper tier
  shows a worse zero-outcome rate. `no_regression_check.downgrade_unsafe`
  reports the current verdict (`false` on this dataset).

---

## `GET /quadrant`

Single slice, Growing/Stalled × Efficient/Wasteful.

Request: `/quadrant?lob_id=insurance&tool_id=claims_triage_agent&week_from=1&week_to=6`

```jsonc
{
  "lob_id": "insurance",
  "tool_id": "claims_triage_agent",
  "week_from": 1,
  "week_to": 6,
  "quadrant": "Growing + Wasteful",   // "Growing|Stalled + Efficient|Wasteful", or null
  "signals": {
    "penetration_growth_rate_per_week": 0.2758,
    "penetration_series": [[1, 0.0938], [2, 0.125], /* [week, wau/addressable] */],
    "growing": true,
    "cost_per_session_usd": 0.1972,
    "cost_per_session_slope": -0.00083,
    "peer_p60_cost_per_session_usd": 0.1831,
    "zero_outcome_rate": 0.271,
    "cache_hit_rate": 0.201,
    "wasteful": true
  }
}
```

No data in range → `{"quadrant": null, "reason": "no sessions in range", ...}`
(HTTP 200). Neither `lob_id` nor `tool_id` supplied → 422.

---

## Contract discipline

This is what the Lovable frontend builds against. If a frontend need surfaces a
gap — a missing metric, an awkward shape — that goes back as a **scoped backend
patch** (same pattern as the two seat-utilization patches), not a client-side
workaround that re-implements a backend rule. Regenerate this file from `/docs`
whenever the backend changes.
