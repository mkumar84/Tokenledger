import json
from collections import defaultdict

sessions = [json.loads(l) for l in open("sessions.jsonl")]

def agg(rows, by):
    out = defaultdict(lambda: {"sessions": 0, "cost": 0.0, "users": set(), "zero_outcome": 0})
    for r in rows:
        key = tuple(r[k] for k in by)
        out[key]["sessions"] += 1
        out[key]["cost"] += r["cost_usd"]
        out[key]["users"].add(r["user_id"])
        if r["outcome"] == "none":
            out[key]["zero_outcome"] += 1
    return out

print("=== Arc 1: Insurance claims_triage_agent — wasteful -> efficient ===")
rows = [r for r in sessions if r["tool_id"] == "claims_triage_agent"]
by_week = agg(rows, ["week"])
for wk in [1, 3, 6, 9, 12]:
    d = by_week[(wk,)]
    avg_cost = d["cost"] / d["sessions"] if d["sessions"] else 0
    print(f"  week {wk:2d}: sessions={d['sessions']:3d} users={len(d['users']):3d} "
          f"avg_cost/session=${avg_cost:.3f} zero_outcome_rate={d['zero_outcome']/max(1,d['sessions']):.0%}")

print("\n=== Arc 4: Retail Banking AML alert triage — stalled + wasteful (should stay flat/bad) ===")
rows = [r for r in sessions if r["tool_id"] == "aml_alert_triage"]
by_week = agg(rows, ["week"])
for wk in [1, 6, 12]:
    d = by_week[(wk,)]
    avg_cost = d["cost"] / d["sessions"] if d["sessions"] else 0
    print(f"  week {wk:2d}: sessions={d['sessions']:3d} users={len(d['users']):3d} "
          f"avg_cost/session=${avg_cost:.3f} zero_outcome_rate={d['zero_outcome']/max(1,d['sessions']):.0%}")

print("\n=== Arc 5: Claude Code cache issue — 3 LOBs bad wks1-8, all 4 fine by wk9+ ===")
rows = [r for r in sessions if r["tool_id"] == "claude_code"]
by_lob_week = agg(rows, ["lob_id", "week"])
for lob in ["insurance", "retail_banking", "wealth_management", "commercial_lending"]:
    w4 = by_lob_week[(lob, 4)]
    w10 = by_lob_week[(lob, 10)]
    cache_avg_w4 = sum(r["cache_hit_rate"] for r in rows if r["lob_id"] == lob and r["week"] == 4) / max(1, w4["sessions"])
    cache_avg_w10 = sum(r["cache_hit_rate"] for r in rows if r["lob_id"] == lob and r["week"] == 10) / max(1, w10["sessions"])
    print(f"  {lob:20s} wk4 avg_cache_hit={cache_avg_w4:.2f}  wk10 avg_cache_hit={cache_avg_w10:.2f}")

print("\n=== Arc 6: SaaS MCP Assist — flat ~30% WEEKLY seat utilization (per-week, not cumulative) ===")
rows = [r for r in sessions if r["tool_id"] == "saas_mcp_assist"]
by_lob_week = agg(rows, ["lob_id", "week"])
for lob in ["insurance", "retail_banking", "wealth_management", "commercial_lending"]:
    weekly_utils = [len(by_lob_week[(lob, wk)]["users"]) / 25 * 100 for wk in WEEKS] if False else None
for lob in ["insurance", "retail_banking", "wealth_management", "commercial_lending"]:
    utils = []
    for wk in range(1, 13):
        d = by_lob_week[(lob, wk)]
        utils.append(len(d["users"]) / 25 * 100)
    avg_util = sum(utils) / len(utils)
    print(f"  {lob:20s} avg_weekly_seat_utilization={avg_util:.0f}%  (wk1={utils[0]:.0f}%, wk12={utils[-1]:.0f}%)")

print("\n=== Arc 8: Cursor in Commercial Lending — legitimate variance, high tokens but good outcomes ===")
rows = [r for r in sessions if r["tool_id"] == "cursor" and r["lob_id"] == "commercial_lending"]
avg_tokens_out = sum(r["tokens_out"] for r in rows) / len(rows)
zero_rate = sum(1 for r in rows if r["outcome"] == "none") / len(rows)
print(f"  avg_tokens_out/session={avg_tokens_out:.0f} (high, by design)  zero_outcome_rate={zero_rate:.0%} (should be low)")

print(f"\nTotal sessions: {len(sessions)}")
print(f"Total simulated spend: ${sum(r['cost_usd'] for r in sessions):,.2f}")
