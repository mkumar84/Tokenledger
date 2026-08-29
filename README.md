# TokenLedger — Backend Engines

Enterprise **AI Tokenomics & Adoption FinOps Copilot** for the fictional
**Northbridge Financial Group** (Insurance, Retail Banking, Wealth Management,
Commercial Lending). Portfolio project, **synthetic data only** — not wired to
any real billing API. Modelled on Uber's *"Running a Software Factory
Efficiently at Uber Scale"* (six-term cost decomposition, adoption-funnel
discipline, anti-pattern dashboard), extended with an adoption-metrics layer and
a dual-dimension **LOB × Tool** tracking model.

This phase = the four backend engines + the API contract. No frontend yet.

## Quick start

```bash
pip install -r requirements.txt
python run.py                 # http://localhost:8000/docs
pytest -q                     # 58 tests, incl. all 8 planted-arc assertions
```

Data lives in [`data/`](data/) (`sessions.jsonl`, `manifest.json`) copied from
the validated generator. **The generator and data files are not modified** —
`data/generate_sessions.py` and `data/validate.py` are kept for reference only.

## The four engines

One design rule everywhere: **`group_by` ∈ {`lob`, `tool`, `lob_tool`} is a
dimension selector, never a branched code path.** `lob_id` (4 values) and
`tool_id` (8 values) are independent dimensions.

### 1. Cost Equation Engine — `tokenledger/engines/cost.py`

Per week, per slice:

```
Total Spend = Users × Sessions/User × Turns/Session × Requests/Turn × Tokens/Request × Price/Token
```

The six factors are defined so their product **reconstructs total spend exactly**
(`reconciles: true` on every row; asserted in tests).

**Driver decomposition** (`/cost/drivers`) attributes the spend delta between
two week-ranges sequentially to four buckets — adoption (users), engagement
(sessions/user), input-token workload, output-token workload — with a **zero
residual** (asserted). Waterfall over
`spend = users × sessions/user × (input$/session + output$/session)`.

### 2. Adoption Engine — `tokenledger/engines/adoption.py`

Per slice, per week: **WAU**, **WoW growth**, **activation rate** (≥3 sessions in
the first 2 weeks of the user's cohort), **sessions/user/week**, **retention**
(prior-week actives still active).

- **Non-human session share** — stubbed to `0.0`. v1 data is 100%
  human-initiated; managed-agent-initiated sessions are *not* fabricated.
- **Seat utilization** — tool-dimension slices only (`group_by` `tool` /
  `lob_tool`). `active_users ÷ licensed_seats`, reported as a **percentage** and
  a **`wasted_seat_cost_usd`** (`unused_seats × cost_per_seat`). Any tool whose
  `tool_registry` entry declares `seats_per_lob` gets this treatment — presence
  of the field, not the tool name (`saas_mcp_assist`: 25/LOB, `cursor`: 20/LOB).
  `group_by=tool` sums seats across all 4 LOBs. Tools with a `cost_per_seat` but
  no `seats_per_lob` report `active_users` with a note.

### 3. Anti-Pattern Detector — `tokenledger/engines/antipattern.py`

Scores each `(lob_id, tool_id, week)` aggregate; every finding carries **both**
`lob_id` and `tool_id`; consecutive flagged weeks collapse into ranges.

| # | Category | Signal |
|---|----------|--------|
| 1 | `suboptimal_model_routing` | frontier model on short, low-output sessions |
| 2 | `context_window_bloat` | mean `tokens_in` ≫ tool fleet baseline |
| 3 | `cache_expiration_churn` | mean `cache_hit_rate` ≪ tool fleet baseline |
| 4 | `prompt_initialization_overhead` | **n/a at session level — not scored** |
| 5 | `chatty_tool_use` | mean `requests_per_turn` ≫ baseline (no planted variance in v1) |
| 6 | `reasoning_effort_mismatch` | `reasoning_effort=high` on short, low-output sessions |
| 7 | `zero_outcome_sessions` | `outcome == "none"`, tagged with the dollar cost |

- **Tool-level rollup** — an anti-pattern in **≥3 of 4 LOBs** for the same tool
  over overlapping weeks becomes **one** tool-level finding (owner = tool owner),
  and the per-LOB findings are marked `rolled_up_into_tool_finding`. The
  `claude_code` cache arc collapses to a single 3-LOB finding.
- **Legitimate-variance exclusion** — a high-token slice whose **outcome rate is
  normal** is a different workload, not waste. Deciding signal is outcome rate,
  never raw token volume. `cursor` in Commercial Lending (big documents, good
  outcomes) lands in `legitimate_variance_exclusions`, not the waste list.

Baselines are computed over the **full fleet history** for the tool, regardless
of the query's week window.

### 4. Recommendation Engine — `tokenledger/engines/recommendation.py`

Joins Adoption + Anti-Pattern output into **one ranked list**. Each rec has:
dollar and/or adoption impact (labelled), an **unambiguous owner** (LOB owner or
tool owner), a **quadrant** where a slice is involved, and a **one-line
remediation**.

**Recommendation sources & actions:**

| source | action | what it is |
|--------|--------|------------|
| `anti_pattern.tool_level_rollup` | (fix) | one platform-level fix for an anti-pattern hitting ≥3 LOBs |
| `anti_pattern.lob_level` | (fix) | a per-LOB anti-pattern above the materiality floor |
| `adoption.seat_utilization` | `consolidate` | seat-licensed tool whose utilization is flat-low across the whole window **and** the recent trend — actionable, carries a `wasted_seat_cost_usd` dollar impact |
| `adoption.seat_utilization` | `monitor` | full-history utilization is below the ceiling but the last `SEAT_UTIL_TREND_WEEKS` (3) weeks clear it — an early-adoption ramp, not idle licences. A **status note**: no dollar-impact claim, does not count toward action-item totals |
| `quadrant` | (enablement / deprecation) | Stalled+Efficient → enablement push; Stalled+Wasteful → deprecation review |
| `governance.tool_shape_similarity` | (consolidate) | two same-category tools with a near-identical usage shape in a single LOB |

The `consolidate` vs `monitor` split on seat utilization mirrors the
anti-pattern detector's legitimate-variance exclusion: don't fire an action rec
off an average when the trend tells a different story. It is driven by
`seats_per_lob` presence in `tool_registry`, not by tool name.

**Quadrant** (`tokenledger/engines/quadrant.py`) — Growing/Stalled × Efficient/
Wasteful, from WoW adoption growth + cost-per-session level & trend:

- *Growing/Stalled*: normalised slope of WAU-penetration (WAU ÷ addressable
  users) over the post-onboarding window. Cohort onboarding completes ~week 9
  and is identical across slices, so it is not counted as growth.
- *Efficient/Wasteful*: zero-outcome rate, cost/session vs peer p60, cache rate,
  cost/session trend.

**Quality gates:**
- *Materiality* — tactical per-slice recs need > **$8/week** impact (calibrated
  to Northbridge's synthetic scale; override with
  `TOKENLEDGER_MATERIALITY_USD_PER_WEEK`) **or** > 10% adoption move. Systemic
  recs (cross-LOB platform rollups, licence governance, deprecation,
  consolidation) bypass the dollar floor — they are one-time structural fixes.
- *No-regression* — never recommend a cheaper model for a slice where outcome
  rate would plausibly drop; checked against zero-outcome rates on the cheaper
  tier elsewhere in the dataset (`no_regression_check` in the response).

## API

**Full locked contract for the frontend build: [`API_CONTRACT.md`](API_CONTRACT.md)**
(generated against the running app — regenerate it from `/docs` after any
backend change).

Read-only. `week_from` / `week_to` are inclusive and optional (default = full
history) unless noted.

| Endpoint | Params |
|----------|--------|
| `GET /cost` | `group_by=lob\|tool\|lob_tool`, `week_from`, `week_to` |
| `GET /cost/drivers` | `group_by`, `a_from`, `a_to`, `b_from`, `b_to` (all required) |
| `GET /adoption` | `group_by=lob\|tool\|lob_tool`, `week_from`, `week_to` |
| `GET /anti-patterns` | `group_by=lob\|tool`, `week_from`, `week_to` |
| `GET /recommendations` | `week_from`, `week_to` |
| `GET /quadrant` | `lob_id` and/or `tool_id` (≥1 required), `week_from`, `week_to` (required) |
| `GET /health` | — |

OpenAPI docs at `/docs`. Deploy: `railway.json` / `Procfile` provided
(`healthcheckPath: /health`); `TOKENLEDGER_DATA_DIR` overrides the data path.

## Testing (brief §4)

`tests/test_planted_arcs.py` iterates `manifest.json`'s `planted_arcs` and
asserts each engine surfaces the `intended_finding` directionally. All 8 arcs
are covered (a meta-test asserts none is left uncovered):

| Arc | Asserted by |
|-----|-------------|
| insurance claims_triage wasteful→efficient | quadrant `Growing+Wasteful` (wk 1-6) → `Growing+Efficient` (wk 9-12); anti-patterns present early, gone late |
| commercial_lending credit_memo stalled+efficient | quadrant `Stalled+Efficient`; enablement rec, adoption impact |
| wealth_management portfolio_summarizer reference | quadrant `Growing+Efficient`; WAU > 2× |
| retail_banking aml_alert_triage stalled+wasteful | quadrant `Stalled+Wasteful`; deprecation rec |
| claude_code cache-expiration cross-LOB | one tool-level rollup covering exactly 3 LOBs; no standalone per-LOB findings |
| saas_mcp_assist underutilized seats | avg utilization < 55%, flat across all 12 wks (recent trend also low); `action: consolidate`, `wasted_seat_cost_usd` > $1k |
| cursor seat utilization (adoption ramp) | avg < 60% but recent 3-wk trend ≥ 60% → `action: monitor`, not `consolidate`; no dollar-impact claim |
| cursor/claude_code consolidation (wealth) | `governance.tool_shape_similarity` rec, wealth_management, mean axis rel-diff < 0.1 |
| cursor commercial_lending legitimate variance | **not** flagged as context bloat; appears in `legitimate_variance_exclusions` |

## Flags back to the spec owner

1. **`MODEL_PRICING` is duplicated** from `generate_sessions.py` into
   `tokenledger/reference.py`. `sessions.jsonl` carries `model` and `cost_usd`
   but not the input/output price split, which the Cost Equation driver
   decomposition needs. Mitigation: output cost is computed exactly from the
   table, input cost is taken as the residual (`cost_usd − output_cost`) so
   per-session totals always reconcile. **Ask:** add `price_in`/`price_out` to
   the schema, or publish `MODEL_PRICING` in `manifest.json`.
2. **No `cohort_start_week` in the schema.** Activation rate needs each user's
   onboarding week. Proxy used: the first week a user is observed active in the
   slice. Stable under the deterministic generator but not identical to the
   generator's `cohort_start_week`. **Ask:** expose `cohort_start_week` (per user
   or as a roster file) if exact activation cohorts matter.

*Resolved in the Phase 1 patch:* `cursor` now declares `seats_per_lob: 20` in
`tool_registry`; the loader picks up `seats_per_lob` from any registry entry by
field presence, so seat utilization + wasted-$ compute for `cursor` with no
name special-casing.

No schema changes, no generator changes, no 5th dimension were made.
