# TokenLedger API Contract (locked — Phase 1)

Authoritative reference for the Lovable frontend build. **This document is
generated against the running FastAPI app** (Patch 3), not from
memory — where it disagrees with an earlier hand-written draft, this document
wins. Re-verify against `GET /docs` (OpenAPI) after any backend change.

- Base: the deployed Railway URL, or `http://localhost:8000` locally.
- All endpoints are **GET**, read-only, no auth, synthetic data.
- Interactive docs: `/docs`. Machine-readable schema: `/openapi.json`.
- Data covers **weeks 1–12**, 4 LOBs, 8 tools, 4231 sessions (`GET /health`).

### Patch 3 additions (additive, no breaking changes)

- **CORS**: the API now sends CORS headers. Allowed browser origins come from
  the `TOKENLEDGER_CORS_ORIGINS` env var (comma-separated exact origins); with
  it unset only localhost dev origins are allowed. **The Railway deployment
  must set `TOKENLEDGER_CORS_ORIGINS` to the real Lovable origin(s)**
  (e.g. `https://tokenledger.lovable.app,https://preview--tokenledger.lovable.app`).
  `GET /health` echoes the active list. `allow_credentials` is `false`;
  methods `GET, OPTIONS`.
- **`/adoption`**: each slice gains a `funnel` object (5-stage snapshot).
- **`/quadrant`**: gains batch mode (bare call, or `lob_ids` / `tool_ids`
  lists). Single-slice calls are unchanged.

### Patch 5 (spend reconciliation — consumption vs. license)

- **`/cost` `total_spend_usd` is now a combined figure.** The six-term equation
  is consumption-only (`users × … × price/token`); it cannot represent a flat
  seat-license fee. `/cost` now returns `consumption_spend_usd` (six-term,
  reconciles), `license_spend_usd` (additive, `seats × rate × weeks`), and
  `total_spend_usd = consumption + license`. The `slices[]` six-term breakdown
  is **unchanged and still consumption-only**.
- **`cost_per_seat` in the registry is $/seat/MONTH.** Anything reported against
  a week range is weekly-converted: `cost_per_seat / 4.345` (weeks per month).
- **`/adoption` `seat_utilization` field renames**: `cost_per_seat_usd` →
  `cost_per_seat_month_usd`; new `cost_per_seat_week_usd`; `wasted_seat_cost_usd`
  → `wasted_seat_cost_week_usd` (now genuinely weekly).
- **`/recommendations` seat recs**: `dollar_impact_per_week_usd` = weekly
  recoverable licence spend; `dollar_impact_usd` = that × window weeks (so it
  stays below `/cost total_spend_usd`). Evidence renames:
  `wasted_seat_cost_usd` → `wasted_seat_cost_week_usd` + `wasted_seat_cost_window_usd`.
- **`/cost/drivers`** gains a 5th `drivers.license_usd` bucket + `total_delta_usd`
  + `fleet_license_delta_usd`. The 4 consumption drivers still sum to
  `delta_usd` (residual 0); all 5 sum to `total_delta_usd`. `license_usd` is 0
  unless the two periods differ in week count.
- **Enforced invariant** (`tests/test_cost.py`): for any window,
  `total_spend_usd ≥ Σ dollar_impact_usd of all recommendations`.
- **Corrected 12-week figures**: consumption **$108.85**, license **$25,408.51**
  (cursor $8,837.74 + saas_mcp_assist $16,570.77), total **$25,517.36**.

### Patch 4 (classification-scope bug fix)

- **`/quadrant` gains a `layer` param** (`L1_managed_agent` | `L2_team_skill` |
  `L3_interactive_harness` | `L4_adhoc`). It restricts the classification to
  sessions of that layer.
- **The Group Overview "LOB × Agent" chart must call
  `GET /quadrant?layer=L1_managed_agent&week_from=&week_to=`** and plot the
  `results[]` rows where **both** `lob_id` and `tool_id` are non-null — one
  point per (LOB, managed agent). The bare-batch `tool_id: null` rows are a
  **whole-LOB blend of every tool** (managed agents + `claude_code` + `cursor`
  + `saas_mcp_assist`) and must **not** be used for any agent-level view — that
  blend is what made Retail Banking read "Growing + Efficient" while its only
  managed agent was "Stalled + Wasteful".
- **`/health` gains `tool_categories` and `lob_managed_agents`** so the frontend
  can build the chart axes and tell managed agents from interactive tools.
- Interactive-tool quadrant positioning belongs on the **Tool view**
  (`?layer=L3_interactive_harness` / `L4_adhoc`, or the plain
  `?tool_ids=…` batch), never mixed into the LOB × Agent chart.

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
| `seat_info: null` for non-seat tools | `seat_utilization` is still an object: `{"licensed_seats": null, "active_users": N, "note": "...", "cost_per_seat_month_usd": null}`. Test `licensed_seats !== null`, not `seat_utilization !== null`. |
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
| `lob_id`, `tool_id` | `/quadrant` | string | no | — | singular → single-slice flat response |
| `lob_ids`, `tool_ids` | `/quadrant` | CSV string | no | — | plural → batch response; bare `/quadrant` = batch over everything |
| `layer` | `/quadrant` | `L1_managed_agent` \| `L2_team_skill` \| `L3_interactive_harness` \| `L4_adhoc` | no | — | scope to one session layer; works with single **and** batch |
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
            "portfolio_summarizer", "saas_mcp_assist"],
  "tool_categories": {                 // Patch 4 — needed for the LOB × Agent chart
    "claims_triage_agent": "managed_agent",
    "claude_code": "interactive_dev_harness",
    "saas_mcp_assist": "saas_mcp"
    // … one entry per tool
  },
  "lob_managed_agents": {               // Patch 4
    "insurance": ["claims_triage_agent", "fraud_ring_detector"],
    "retail_banking": ["aml_alert_triage"],
    "wealth_management": ["portfolio_summarizer"],
    "commercial_lending": ["credit_memo_agent"]
  },
  "cors_allowed_origins": ["http://localhost:5173", "..."]
}
```

`GET /` returns `{"service", "version", "endpoints": [...]}`.

---

## `GET /cost`

Six-term **consumption** decomposition per slice per week, **plus** the additive
seat-license spend (Patch 5).
`consumption = Users × Sessions/User × Turns/Session × Requests/Turn × Tokens/Request × Price/Token`
`total_spend_usd = consumption_spend_usd + license_spend_usd`

```jsonc
{
  "engine": "cost_equation",
  "group_by": "lob_tool",
  "week_from": 1,
  "week_to": 12,
  "equation": "Users x Sessions/User x Turns/Session x Requests/Turn x Tokens/Request x Price/Token",

  "consumption_spend_usd": 108.85,      // six-term, = sum of slice-week total_spend_usd
  "license_spend_usd": 25408.51,        // additive; seats x (monthly/4.345) x weeks
  "total_spend_usd": 25517.36,          // consumption + license
  "consumption_reconciles": true,       // every slice-week six-term breakdown reconstructs itself
  "cost_model": {
    "consumption": "six-term multiplicative (the `slices` below)",
    "license": "additive: seats_per_lob x lobs x (cost_per_seat_month / weeks_per_month) x weeks_in_window",
    "weeks_per_month": 4.345
  },
  "license_spend_detail": [
    { "tool_id": "cursor", "seats_per_lob": 20, "lobs": 4, "seats_total": 80,
      "cost_per_seat_month_usd": 40, "cost_per_seat_week_usd": 9.206,
      "weeks": 12, "license_spend_usd": 8837.74, "license_spend_per_lob_usd": 2209.44 },
    { "tool_id": "saas_mcp_assist", "seats_total": 100, "cost_per_seat_month_usd": 60,
      "cost_per_seat_week_usd": 13.809, "weeks": 12, "license_spend_usd": 16570.77 }
  ],

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

Frontend:
- The six factors × each other = the slice-week's `total_spend_usd`
  (consumption); `reconciles` / `consumption_reconciles` are quiet integrity
  checks, not headline metrics.
- The **`slices[]` block is consumption-only** — do not add `license_spend_usd`
  into it. Show `consumption_spend_usd` / `license_spend_usd` / `total_spend_usd`
  as three distinct top-line numbers (a licence-heavy fleet is a real finding,
  not noise to blend away).
- `license_spend_usd` is the same for any `group_by` and any weeks in the
  window — it is a fleet figure keyed only to seat counts × window length.

---

## `GET /cost/drivers`

Two-period **consumption** waterfall; the four consumption drivers sum to
`delta_usd` with **zero residual**. `license_usd` is a separate 5th bucket.

Request: `/cost/drivers?group_by=lob_tool&a_from=1&a_to=4&b_from=9&b_to=12`

```jsonc
{
  "engine": "cost_equation.driver_decomposition",
  "group_by": "lob_tool",
  "period_a_weeks": [1, 4],
  "period_b_weeks": [9, 12],
  "consumption_drivers": ["adoption_users_usd", "engagement_sessions_per_user_usd",
                          "input_token_workload_usd", "output_token_workload_usd"],
  "fleet_license_delta_usd": 0.0,   // seat-count-driven; 0 unless the periods differ in week count
  "license_note": "…",
  "slices": [
    {
      "lob_id": "insurance",
      "tool_id": "claims_triage_agent",
      "spend_a_usd": 0.8137,
      "spend_b_usd": 1.8883,
      "delta_usd": 1.0746,               // CONSUMPTION delta (unchanged meaning)
      "total_delta_usd": 1.0746,         // delta_usd + drivers.license_usd
      "drivers": {
        "adoption_users_usd": 0.8137,
        "engagement_sessions_per_user_usd": 0.3551,
        "input_token_workload_usd": -0.0487,
        "output_token_workload_usd": -0.0455,
        "license_usd": 0.0               // 5th bucket; not part of the consumption waterfall
      },
      "residual_usd": 0.0        // delta_usd − sum(4 consumption drivers); ~0 (may serialize -0.0)
    }
  ]
}
```

`sum(4 consumption drivers) == delta_usd` (residual 0). `sum(all 5) ==
total_delta_usd`. With static simulated seat counts `license_usd` is 0 whenever
the two periods have the same number of weeks.

Waterfall: `spend_a_usd` → +/− the four `drivers` → `spend_b_usd`.

---

## `GET /adoption`

Per slice: `funnel` (snapshot) + `activation_by_cohort_week` (once) + `weeks[]` (per week).

```jsonc
{
  "engine": "adoption",
  "group_by": "tool",
  "week_from": 1,
  "week_to": 12,
  "slices": [
    {
      "tool_id": "cursor",                    // only the grouped dim key(s)
      "funnel": {                             // 5-stage snapshot as of the last week in the range
        "as_of_week": 12,
        "eligible": 104,        // addressable roster: users_per_lob for a LOB slice;
                                //   sum over LOBs that use the tool for a tool slice
        "onboarded": 100,       // >=1 session in the slice by as_of_week
        "activated": 41,        // >=3 sessions in the first 2 weeks of the user's cohort
        "habitual": 7,          // activated AND a run of >=4 consecutive weekly-active weeks
        "power_user": 3,        // habitual AND top 10% of sessions/active-week within the slice
        "definitions": { "eligible": "...", "onboarded": "...", /* ... */ }
      },
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
            "cost_per_seat_month_usd": 40,     // registry value ($/seat/MONTH)
            "cost_per_seat_week_usd": 9.206,   // = monthly / 4.345
            "wasted_seat_cost_week_usd": 267.0 // unused_seats × cost_per_seat_week_usd (this block is per-week)
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
  `{"licensed_seats": null, "active_users": N, "note": "no licensed seat count declared for this tool", "cost_per_seat_month_usd": null}`.
- `group_by=lob`: key is **absent** entirely.

Detect "has seat data" via `seat_utilization?.licensed_seats != null`.
There is **no trend field here** — recent-trend lives in `/recommendations`.

**`funnel`** — a monotonically non-increasing 5-stage snapshot
(`eligible >= onboarded >= activated >= habitual >= power_user`, each stage a
subset of the previous). Computed over each user's full history up to
`as_of_week` (= the range's last week), so `week_from` does not truncate the
consecutive-week runs used for `habitual`. `power_user`'s decile threshold is
computed **within the slice** (LOB / tool / lob_tool per `group_by`), not
globally. Present on every slice, every `group_by`.

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
      "dollar_impact_usd": 12455.76,            // recoverable licence spend OVER THE WINDOW
      "dollar_impact_per_week_usd": 1037.98,    // recoverable licence spend PER WEEK
      "adoption_impact": null,                  // string when impact_type involves adoption
      "quadrant": null,                         // "Growing + Wasteful" etc., or null
      "remediation": "Right-size to ~25% utilised seat count …",  // always a non-empty string
      "evidence": {                             // shape varies by source (see below)
        "avg_seat_utilization_pct": 24.8,
        "recent_trend_pct": 31.0,
        "trend_window_weeks": 3,
        "wasted_seat_cost_week_usd": 1037.98,
        "wasted_seat_cost_window_usd": 12455.76,
        "window_weeks": 12
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
| `adoption.seat_utilization` | `consolidate` \| `monitor` | — | `{avg_seat_utilization_pct, recent_trend_pct, trend_window_weeks, wasted_seat_cost_week_usd, wasted_seat_cost_window_usd, window_weeks}` |
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

Growing/Stalled × Efficient/Wasteful. `week_from` and `week_to` are **required**.

### Mode selection

| Request | Mode | Response |
|---|---|---|
| `?lob_id=X&week_from=&week_to=` | single | **flat object** (below) |
| `?tool_id=Y&week_from=&week_to=` | single | flat object |
| `?lob_id=X&tool_id=Y&week_from=&week_to=` | single | flat object |
| `?week_from=&week_to=` (no id filter) | batch — all | `{results: [...]}` for every LOB, every tool, every populated (lob,tool) cell |
| `?layer=L1_managed_agent&week_from=&week_to=` | batch — agent | `{results: [...]}` for every LOB (its managed-agent aggregate) + every (LOB, managed_agent) cell — **the LOB × Agent chart** |
| `?lob_ids=a,b&week_from=&week_to=` | batch | `{results: [...]}` — those LOBs, LOB-level |
| `?tool_ids=a,b&week_from=&week_to=` | batch | `{results: [...]}` — those tools, tool-level |
| `?lob_ids=a,b&tool_ids=c,d&week_from=&week_to=` | batch | `{results: [...]}` — the cross-product cells |

`layer` combines with any of the above (single or batch) to restrict the
classification to one session layer.

The singular `lob_id` / `tool_id` params keep the **exact pre-Patch-3 flat
shape** (no `results` key). The plural `lob_ids` / `tool_ids` params (or no id
param at all) trigger batch mode. Not a breaking change: bare `/quadrant` used
to 422, now returns the all-slices batch.

**Scope matters — read this before wiring a chart.** `/quadrant?lob_id=X` (and
the bare-batch `tool_id: null` rows) classify **every session in the LOB across
every tool** — managed agents blended with `claude_code`, `cursor`,
`saas_mcp_assist`. A healthy interactive-tool footprint will mask a wasteful or
stalled managed agent. For any **agent-level** view pass
`layer=L1_managed_agent` and use the `(lob_id, tool_id)` cells.

### Single-slice (flat) response

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

No data in range → `{"quadrant": null, "reason": "no sessions in range", ...}` (HTTP 200).

### Batch response

Request: `/quadrant?week_from=1&week_to=12`

```jsonc
{
  "week_from": 1,
  "week_to": 12,
  "count": 29,
  "results": [
    { "lob_id": "insurance", "tool_id": null, "quadrant": "Stalled + Efficient", "signals": { … } },
    { "lob_id": null, "tool_id": "cursor", "quadrant": "Growing + Efficient", "signals": { … } },
    { "lob_id": "insurance", "tool_id": "claude_code", "quadrant": "Growing + Efficient", "signals": { … } }
    // … LOB-level rows (tool_id null), tool-level rows (lob_id null), then cells
  ]
}
```

Each `results[]` entry is exactly the single-slice flat shape (minus the
echoed `week_from`/`week_to`); rows carry `"layer"` only when the request set it.
Empty cells are omitted from a bare batch; request them explicitly with
`lob_ids=…&tool_ids=…` to get a `quadrant: null` row for a checked-but-empty cell.

**Group Overview "LOB × Agent" chart** — one call:

```
GET /quadrant?layer=L1_managed_agent&week_from=1&week_to=12
```

`results[]` then contains, for that window:

| filter | use |
|---|---|
| `lob_id && tool_id` (cells) | one point per (LOB, managed agent) — this is the chart. Insurance has two (`claims_triage_agent`, `fraud_ring_detector`). |
| `lob_id && !tool_id` | the LOB's managed-agent aggregate, if you want a single dot per LOB |

Verified against the planted arcs (weeks 1–12): Insurance/`claims_triage_agent`
→ Growing + Efficient, Retail Banking/`aml_alert_triage` → **Stalled +
Wasteful**, Wealth Mgmt/`portfolio_summarizer` → Growing + Efficient, Commercial
Lending/`credit_memo_agent` → Stalled + Efficient. Use `week_from=1&week_to=6`
vs `9&12` to show the claims-triage transition.

**LOB × Tool matrix** (interactive tools): `GET /quadrant?week_from=1&week_to=12`
(no layer) and filter to `(lob_id, tool_id)` cells, or scope to
`?layer=L3_interactive_harness`. Do not use the `tool_id: null` rows for any
per-agent or per-tool view — they are whole-LOB blends.

---

## Contract discipline

This is what the Lovable frontend builds against. If a frontend need surfaces a
gap — a missing metric, an awkward shape — that goes back as a **scoped backend
patch** (same pattern as the two seat-utilization patches), not a client-side
workaround that re-implements a backend rule. Regenerate this file from `/docs`
whenever the backend changes.
