"""
TokenLedger Synthetic Session-Trace Generator
Northbridge Financial Group (fictional, multi-LOB, multi-tool)
Spec reference: TokenLedger_Spec_v6.md, sections 2.2, 2.3, 9.1-9.3

Produces:
  sessions.jsonl   - one session-trace event per line
  manifest.json    - declares every planted story arc (LOB and Tool level)

Deterministic (fixed seed) per spec decision v6 §0.2.1.
Simulated history: 12 weeks.
"""

import json
import random
from pathlib import Path

SEED = 42
random.seed(SEED)

OUT_DIR = Path(__file__).parent
WEEKS = list(range(1, 13))  # 12 simulated weeks

# ---------------------------------------------------------------------------
# 1. Reference data — LOBs, Tools, Agents, Model pricing (§2.2, §2.3)
# ---------------------------------------------------------------------------

LOBS = ["insurance", "retail_banking", "wealth_management", "commercial_lending"]

# Tool registry (§2.3) — cost_per_seat added per v6 §0.2 decision #2
TOOL_REGISTRY = {
    "claude_code": {
        "name": "Claude Code", "category": "interactive_dev_harness",
        "pricing_model": "per_token", "cost_per_seat": None,
        "owner": "Group Platform Eng",
    },
    "cursor": {
        "name": "Cursor", "category": "interactive_dev_harness",
        "pricing_model": "seat_plus_usage", "cost_per_seat": 40,
        "owner": "Group Platform Eng",
    },
    "saas_mcp_assist": {
        "name": "SaaS Workspace Assistant", "category": "saas_mcp",
        "pricing_model": "seat_license_plus_usage", "cost_per_seat": 60,
        "owner": "Group Platform Eng",
    },
    # Managed agents (L1), one primary per LOB (spec §2.3 example set + fraud_ring_detector)
    "claims_triage_agent": {
        "name": "Claims Triage Agent", "category": "managed_agent",
        "pricing_model": "per_token", "cost_per_seat": None,
        "owner": "Insurance AI Lead",
    },
    "fraud_ring_detector": {
        "name": "Fraud Ring Detector", "category": "managed_agent",
        "pricing_model": "per_token", "cost_per_seat": None,
        "owner": "Insurance AI Lead",
    },
    "aml_alert_triage": {
        "name": "AML Alert Triage", "category": "managed_agent",
        "pricing_model": "per_token", "cost_per_seat": None,
        "owner": "Retail Banking AI Lead",
    },
    "portfolio_summarizer": {
        "name": "Portfolio Summarizer", "category": "managed_agent",
        "pricing_model": "per_token", "cost_per_seat": None,
        "owner": "Wealth Management AI Lead",
    },
    "credit_memo_agent": {
        "name": "Credit Memo Drafting Agent", "category": "managed_agent",
        "pricing_model": "per_token", "cost_per_seat": None,
        "owner": "Commercial Lending AI Lead",
    },
}

# Which LOB "owns" each managed agent (L1). Interactive tools (claude_code,
# cursor, saas_mcp_assist) are used BY every LOB — that's the point of the
# independent-dimension design (§2.2).
LOB_MANAGED_AGENTS = {
    "insurance": ["claims_triage_agent", "fraud_ring_detector"],
    "retail_banking": ["aml_alert_triage"],
    "wealth_management": ["portfolio_summarizer"],
    "commercial_lending": ["credit_memo_agent"],
}

INTERACTIVE_TOOLS = ["claude_code", "cursor", "saas_mcp_assist"]

# Fictional per-1K-token pricing, input/output, by model tier
MODEL_PRICING = {
    "frontier-large": {"input": 0.015, "output": 0.075},
    "frontier-medium": {"input": 0.003, "output": 0.015},
    "efficient-small": {"input": 0.0005, "output": 0.0025},
}

# ---------------------------------------------------------------------------
# 2. Users & teams — cohort-staggered onboarding for realistic activation (§9.1)
# ---------------------------------------------------------------------------

TEAM_SIZE_BY_LOB = {
    "insurance": 32,
    "retail_banking": 40,      # larger, junior-heavy per spec §4.2
    "wealth_management": 18,
    "commercial_lending": 14,  # smaller, senior-heavy per spec §4.2
}

COHORT_WEEKS = [1, 1, 1, 3, 3, 6, 9]  # weighted toward week 1, staggered onboarding

def build_users():
    users = {}
    uid = 1
    for lob in LOBS:
        n = TEAM_SIZE_BY_LOB[lob]
        for _ in range(n):
            cohort = random.choice(COHORT_WEEKS)
            users[f"u{uid:04d}"] = {"lob_id": lob, "team_id": f"{lob}_team",
                                     "cohort_start_week": cohort}
            uid += 1
    return users

USERS = build_users()

def users_in_lob(lob, active_only_from_week=None):
    ids = [uid for uid, u in USERS.items() if u["lob_id"] == lob]
    if active_only_from_week is not None:
        ids = [uid for uid in ids if USERS[uid]["cohort_start_week"] <= active_only_from_week]
    return ids

# ---------------------------------------------------------------------------
# 3. Planted story arcs (§9.2 in v3/v4, §0.2 decision #3 in v6)
# ---------------------------------------------------------------------------
# Each arc function takes a week number and returns a "profile" dict used to
# sample individual sessions. Arc functions are the single source of truth —
# manifest.json is generated FROM these, not maintained separately.

def clamp(v, lo, hi):
    return max(lo, min(hi, v))

# --- Arc 1: Insurance managed agent (claims_triage_agent) ------------------
# Growing+Wasteful weeks 1-6 -> cache-TTL fix week 7 -> Growing+Efficient by wk9
def arc_claims_triage(week):
    wau_frac = clamp(0.15 + 0.05 * week, 0.15, 0.9)  # steadily growing adoption
    if week <= 6:
        return dict(wau_frac=wau_frac, sessions_per_user=(1, 3), turns=(6, 14),
                    tokens_in=(3000, 9000), tokens_out=(800, 2500),
                    model="frontier-large", reasoning_effort="high",
                    cache_hit=(0.10, 0.30), zero_outcome_p=0.35)
    elif week == 7:
        # the fix lands mid-week — transition week, mixed profile
        return dict(wau_frac=wau_frac, sessions_per_user=(1, 3), turns=(5, 10),
                    tokens_in=(2500, 6000), tokens_out=(600, 1600),
                    model="frontier-medium", reasoning_effort="medium",
                    cache_hit=(0.30, 0.55), zero_outcome_p=0.22)
    else:
        return dict(wau_frac=wau_frac, sessions_per_user=(1, 3), turns=(3, 7),
                    tokens_in=(1500, 3500), tokens_out=(300, 900),
                    model="frontier-medium", reasoning_effort="medium",
                    cache_hit=(0.55, 0.80), zero_outcome_p=0.08)

# --- Arc 2: Commercial Lending managed agent (credit_memo_agent) -----------
# Stalled+Efficient throughout — low WAU, low waste, flat
def arc_credit_memo(week):
    return dict(wau_frac=0.20, sessions_per_user=(1, 2), turns=(2, 5),
                tokens_in=(1200, 2500), tokens_out=(300, 700),
                model="efficient-small", reasoning_effort="low",
                cache_hit=(0.60, 0.80), zero_outcome_p=0.10)

# --- Arc 3: Wealth Management managed agent (portfolio_summarizer) --------
# Growing+Efficient from week 1 — the reference-implementation baseline
def arc_portfolio_summarizer(week):
    wau_frac = clamp(0.25 + 0.06 * week, 0.25, 0.95)
    return dict(wau_frac=wau_frac, sessions_per_user=(1, 3), turns=(2, 5),
                tokens_in=(1000, 2200), tokens_out=(250, 600),
                model="efficient-small", reasoning_effort="low",
                cache_hit=(0.65, 0.85), zero_outcome_p=0.07)

# --- Arc 4: Retail Banking managed agent (aml_alert_triage) ---------------
# Stalled+Wasteful throughout — deprecation candidate
def arc_aml_alert_triage(week):
    return dict(wau_frac=0.18, sessions_per_user=(1, 2), turns=(7, 15),
                tokens_in=(3500, 8000), tokens_out=(900, 2200),
                model="frontier-large", reasoning_effort="high",
                cache_hit=(0.10, 0.25), zero_outcome_p=0.40)

MANAGED_AGENT_ARCS = {
    "claims_triage_agent": arc_claims_triage,
    "credit_memo_agent": arc_credit_memo,
    "portfolio_summarizer": arc_portfolio_summarizer,
    "aml_alert_triage": arc_aml_alert_triage,
}

# fraud_ring_detector: no planted arc — background/noise-only agent so not
# every agent in the dataset is "a story," which keeps the demo credible.
def arc_fraud_ring_detector(week):
    wau_frac = clamp(0.30 + 0.02 * week, 0.30, 0.55)
    return dict(wau_frac=wau_frac, sessions_per_user=(1, 2), turns=(3, 6),
                tokens_in=(1500, 3000), tokens_out=(400, 900),
                model="frontier-medium", reasoning_effort="medium",
                cache_hit=(0.40, 0.60), zero_outcome_p=0.15)

MANAGED_AGENT_ARCS["fraud_ring_detector"] = arc_fraud_ring_detector

# --- Arc 5 (tool-level): Claude Code cache-expiration churn ---------------
# Shows in insurance, retail_banking, wealth_management (NOT commercial_lending,
# which already runs the 1-hour TTL default). Fixed globally at week 9.
CLAUDE_CODE_CACHE_ISSUE_LOBS = ["insurance", "retail_banking", "wealth_management"]

def arc_claude_code(lob, week):
    has_issue = lob in CLAUDE_CODE_CACHE_ISSUE_LOBS and week < 9
    wau_frac = clamp(0.35 + 0.03 * week, 0.35, 0.85)
    if has_issue:
        return dict(wau_frac=wau_frac, sessions_per_user=(2, 5), turns=(4, 9),
                    tokens_in=(4000, 12000), tokens_out=(600, 1800),
                    model="frontier-medium", reasoning_effort="medium",
                    cache_hit=(0.15, 0.35), zero_outcome_p=0.20)
    else:
        return dict(wau_frac=wau_frac, sessions_per_user=(2, 5), turns=(3, 7),
                    tokens_in=(2000, 5000), tokens_out=(400, 1000),
                    model="frontier-medium", reasoning_effort="medium",
                    cache_hit=(0.60, 0.85), zero_outcome_p=0.10)

# --- Arc 6 (tool-level): SaaS MCP Assist — underutilized seats ------------
# 30% seat utilization, flat, across ALL LOBs, all weeks. 25 seats per LOB.
SAAS_MCP_SEATS_PER_LOB = 25

def arc_saas_mcp_assist(lob, week):
    return dict(wau_frac=0.30, sessions_per_user=(1, 2), turns=(2, 4),
                tokens_in=(800, 1800), tokens_out=(200, 500),
                model="efficient-small", reasoning_effort="low",
                cache_hit=(0.50, 0.70), zero_outcome_p=0.15)

# --- Arc 7 (tool-level, LOB-specific): Cursor/Claude Code consolidation ---
# candidate in wealth_management ONLY — near-identical usage shape.
def arc_cursor(lob, week):
    if lob == "wealth_management":
        # mirror claude_code's healthy profile in this LOB closely
        wau_frac = clamp(0.33 + 0.03 * week, 0.33, 0.83)
        return dict(wau_frac=wau_frac, sessions_per_user=(2, 5), turns=(3, 7),
                    tokens_in=(2000, 5000), tokens_out=(400, 1000),
                    model="frontier-medium", reasoning_effort="medium",
                    cache_hit=(0.60, 0.85), zero_outcome_p=0.10)
    elif lob == "commercial_lending":
        # Arc 8 / v6 decision #3: legitimate variance, NOT an anti-pattern.
        # Larger documents -> naturally higher output tokens, but good outcomes.
        wau_frac = clamp(0.25 + 0.02 * week, 0.25, 0.55)
        return dict(wau_frac=wau_frac, sessions_per_user=(1, 3), turns=(3, 6),
                    tokens_in=(3000, 6000), tokens_out=(2000, 4500),  # naturally high output
                    model="frontier-medium", reasoning_effort="medium",
                    cache_hit=(0.55, 0.75), zero_outcome_p=0.08)  # good outcomes despite high tokens
    else:
        wau_frac = clamp(0.20 + 0.02 * week, 0.20, 0.45)
        return dict(wau_frac=wau_frac, sessions_per_user=(1, 2), turns=(2, 5),
                    tokens_in=(1500, 3000), tokens_out=(300, 700),
                    model="efficient-small", reasoning_effort="low",
                    cache_hit=(0.55, 0.75), zero_outcome_p=0.12)

INTERACTIVE_ARC_FNS = {
    "claude_code": arc_claude_code,
    "cursor": arc_cursor,
    "saas_mcp_assist": arc_saas_mcp_assist,
}

# ---------------------------------------------------------------------------
# 4. Session generation
# ---------------------------------------------------------------------------

session_counter = 1

def emit_sessions(lob, tool_or_agent_id, layer, week, profile):
    global session_counter
    sessions = []
    eligible = users_in_lob(lob, active_only_from_week=week)
    if not eligible:
        return sessions
    wau_target = max(1, round(len(eligible) * profile["wau_frac"]))
    active_users = random.sample(eligible, min(wau_target, len(eligible)))

    for uid in active_users:
        n_sessions = random.randint(*profile["sessions_per_user"])
        for _ in range(n_sessions):
            turn_count = random.randint(*profile["turns"])
            requests_per_turn = random.randint(1, 3)
            tokens_in = random.randint(*profile["tokens_in"])
            tokens_out = random.randint(*profile["tokens_out"])
            cache_hit_rate = round(random.uniform(*profile["cache_hit"]), 2)
            model = profile["model"]
            price = MODEL_PRICING[model]
            # cache reduces effective billed input tokens
            effective_input = tokens_in * (1 - cache_hit_rate * 0.9)
            cost = round((effective_input / 1000) * price["input"]
                          + (tokens_out / 1000) * price["output"], 4)
            outcome = "none" if random.random() < profile["zero_outcome_p"] else random.choice(
                ["merged_pr", "claim_processed", "review_posted", "alert_triaged"]
            )
            sessions.append({
                "session_id": f"s{session_counter:07d}",
                "user_id": uid,
                "team_id": USERS[uid]["team_id"],
                "lob_id": lob,
                "tool_id": tool_or_agent_id,
                "agent_id": tool_or_agent_id if TOOL_REGISTRY[tool_or_agent_id]["category"] == "managed_agent" else None,
                "layer": layer,
                "week": week,
                "turn_count": turn_count,
                "requests_per_turn": requests_per_turn,
                "tokens_in": tokens_in,
                "tokens_out": tokens_out,
                "model": model,
                "reasoning_effort": profile["reasoning_effort"],
                "cache_hit_rate": cache_hit_rate,
                "cost_usd": cost,
                "outcome": outcome,
            })
            session_counter += 1
    return sessions

all_sessions = []

for week in WEEKS:
    for lob in LOBS:
        # Managed agents (L1) — owned by one LOB each
        for agent_id in LOB_MANAGED_AGENTS[lob]:
            profile = MANAGED_AGENT_ARCS[agent_id](week)
            all_sessions += emit_sessions(lob, agent_id, "L1_managed_agent", week, profile)
        # Interactive tools — used by every LOB
        for tool_id in INTERACTIVE_TOOLS:
            profile = INTERACTIVE_ARC_FNS[tool_id](lob, week)
            layer = "L4_adhoc" if tool_id == "saas_mcp_assist" else "L3_interactive_harness"
            all_sessions += emit_sessions(lob, tool_id, layer, week, profile)

# ---------------------------------------------------------------------------
# 5. Write outputs
# ---------------------------------------------------------------------------

sessions_path = OUT_DIR / "sessions.jsonl"
with open(sessions_path, "w") as f:
    for s in all_sessions:
        f.write(json.dumps(s) + "\n")

manifest = {
    "generator_seed": SEED,
    "simulated_weeks": [WEEKS[0], WEEKS[-1]],
    "lobs": LOBS,
    "tool_registry": TOOL_REGISTRY,
    "lob_managed_agents": LOB_MANAGED_AGENTS,
    "total_users": len(USERS),
    "users_per_lob": TEAM_SIZE_BY_LOB,
    "planted_arcs": [
        {
            "arc": "insurance_claims_triage_wasteful_to_efficient",
            "lob": "insurance", "tool_or_agent": "claims_triage_agent",
            "week_range": [1, 6], "transition_week": 7, "resolved_week": 9,
            "intended_finding": "Growing + Wasteful -> cache-TTL & model-tier fix -> Growing + Efficient",
            "type": "lob_level_quadrant",
        },
        {
            "arc": "commercial_lending_credit_memo_stalled_efficient",
            "lob": "commercial_lending", "tool_or_agent": "credit_memo_agent",
            "week_range": [1, 12],
            "intended_finding": "Stalled + Efficient (enablement gap, not a cost problem)",
            "type": "lob_level_quadrant",
        },
        {
            "arc": "wealth_management_portfolio_summarizer_reference",
            "lob": "wealth_management", "tool_or_agent": "portfolio_summarizer",
            "week_range": [1, 12],
            "intended_finding": "Growing + Efficient from week 1 (reference implementation baseline)",
            "type": "lob_level_quadrant",
        },
        {
            "arc": "retail_banking_aml_alert_triage_stalled_wasteful",
            "lob": "retail_banking", "tool_or_agent": "aml_alert_triage",
            "week_range": [1, 12],
            "intended_finding": "Stalled + Wasteful (deprecation candidate)",
            "type": "lob_level_quadrant",
        },
        {
            "arc": "claude_code_cache_expiration_cross_lob",
            "lobs": CLAUDE_CODE_CACHE_ISSUE_LOBS, "tool_or_agent": "claude_code",
            "week_range": [1, 8], "resolved_week": 9,
            "intended_finding": "Cache-expiration churn in 3 of 4 LOBs simultaneously -> tool-level rollup, one platform fix",
            "type": "tool_level_anti_pattern",
        },
        {
            "arc": "saas_mcp_assist_underutilized_seats",
            "lobs": LOBS, "tool_or_agent": "saas_mcp_assist",
            "week_range": [1, 12], "seat_utilization_pct": 30,
            "seats_per_lob": SAAS_MCP_SEATS_PER_LOB, "cost_per_seat": TOOL_REGISTRY["saas_mcp_assist"]["cost_per_seat"],
            "intended_finding": "Flat 30% seat utilization group-wide -> renewal/consolidation recommendation",
            "type": "tool_level_governance",
        },
        {
            "arc": "cursor_claude_code_consolidation_candidate_wealth_mgmt",
            "lob": "wealth_management", "tools": ["cursor", "claude_code"],
            "week_range": [1, 12],
            "intended_finding": "Near-identical usage shape, single LOB -> localized consolidation flag",
            "type": "tool_level_governance",
        },
        {
            "arc": "cursor_commercial_lending_legitimate_variance",
            "lob": "commercial_lending", "tool_or_agent": "cursor",
            "week_range": [1, 12],
            "intended_finding": "Higher output-tokens/session due to larger documents, NOT waste -- good outcome rate preserved. Keeps anti-pattern detector honest.",
            "type": "tool_level_legitimate_variance",
        },
    ],
}

manifest_path = OUT_DIR / "manifest.json"
with open(manifest_path, "w") as f:
    json.dump(manifest, f, indent=2)

print(f"Generated {len(all_sessions)} sessions -> {sessions_path}")
print(f"Manifest -> {manifest_path}")
