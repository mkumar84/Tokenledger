"""'Ask TokenLedger' — grounded natural-language Q&A (Backend Patch 7).

The one rule that matters: **grounded, not generative.** A ``/chat`` answer is a
real Claude API call, but every fact in it must come from the same aggregates
the dashboards render — the cost / adoption / quadrant / recommendation /
anti-pattern engine outputs, assembled in-process for the requested week range.
Never raw session rows; never an aggregate computed here. This is the load-
bearing design decision — a chatbot that recomputes its own numbers becomes a
sixth, eventually-contradictory source of truth.

Read-only: the system prompt forbids phrasing any answer as though an action has
been or will be taken.
"""
from __future__ import annotations

import json
import os
from typing import Any

import anthropic

from .engines import adoption, cost_equation, detect, recommend
from .engines.quadrant import classify_batch

# Haiku 4.5 — a lookup-and-synthesize task over small structured JSON does not
# need a larger model, and a small/fast model keeps latency low for a
# leadership-facing chat. (Bare model id per the Anthropic SDK; no date suffix.)
CHAT_MODEL = "claude-haiku-4-5"
CHAT_MAX_TOKENS = 1024
MAX_HISTORY_MESSAGES = 20

SYSTEM_PROMPT = (
    "You are answering questions about TokenLedger, an AI tokenomics and adoption "
    "dashboard for a fictional financial institution (Northbridge Financial Group). "
    "Answer ONLY using the JSON data provided in this message. Cite the specific "
    "numbers you used. If the question cannot be answered from the provided data — "
    "including forecasts, hypotheticals, or anything requiring information not "
    "present — say so explicitly rather than guessing or estimating. This is a "
    "read-only reporting tool: never phrase an answer as though an action has been "
    "or will be taken automatically.\n\n"
    "When a question requires comparing, ranking, or finding the minimum or maximum "
    "across multiple values, first explicitly list each relevant item with its exact "
    "value on its own line, then state your conclusion referencing those listed "
    "values. Double-check the direction of comparison before answering: 'fewest', "
    "'lowest', 'smallest', and 'least' mean the smallest number; 'most', 'highest', "
    "'largest', and 'greatest' mean the largest number. If you are not confident in a "
    "ranking after listing the values, say which values you compared rather than "
    "stating a conclusion you are unsure of.\n\n"
    "The JSON keys map to dashboard views: `cost_by_lob` (six-term consumption "
    "spend + additive seat-license spend), `adoption_by_lob` / `adoption_by_tool` "
    "(WAU, WoW growth, the 5-stage funnel, seat utilization), "
    "`quadrant_lob_agent` (Growing/Stalled x Efficient/Wasteful per LOB managed "
    "agent — the Group Overview chart), `quadrant_by_tool`, `recommendations` "
    "(ranked, with owner and dollar/adoption impact), and `anti_patterns`."
)


# --- context assembly --------------------------------------------------

def _strip(obj: Any, drop_keys: set[str]) -> Any:
    """Recursively drop verbose nested keys (series, per-week metric dumps)
    that add bytes but not lookup value. Facts are untouched."""
    if isinstance(obj, dict):
        return {k: _strip(v, drop_keys) for k, v in obj.items() if k not in drop_keys}
    if isinstance(obj, list):
        return [_strip(v, drop_keys) for v in obj]
    return obj


_VERBOSE_KEYS = {
    "penetration_series",       # 12-element arrays in quadrant signals
    "per_week",                 # per-week metric dump inside anti-pattern findings
    "weeks_flagged",            # ditto
    "metric",                   # anti-pattern metric dump — `detail` carries the summary
    "rolled_up_lob_findings",   # duplicates the per-LOB findings already listed
    "activation_by_cohort_week",  # cohort table, rarely the subject of a question
    "definitions",              # funnel stage prose — in the system prompt already
}


def _last_week_only(adoption_result: dict[str, Any]) -> dict[str, Any]:
    """Keep each tool slice's funnel + its final-week row (current WAU + seat
    utilization) — the per-week series for every tool is Tool-view detail, not a
    Group Overview grounding need."""
    out = dict(adoption_result)
    slices = []
    for sl in adoption_result["slices"]:
        weeks = sl.get("weeks", [])
        slices.append({**{k: v for k, v in sl.items() if k != "weeks"},
                       "latest_week": weeks[-1] if weeks else None})
    out["slices"] = slices
    out["note"] = "per-tool weekly series omitted; latest_week + funnel retained"
    return out


def build_context(
    week_from: int | None, week_to: int | None
) -> tuple[dict[str, Any], list[str]]:
    """Assemble the grounding bundle from the engines. Returns (bundle,
    grounded_in) where grounded_in names the sources pulled in."""
    recs = _strip(recommend(week_from, week_to), _VERBOSE_KEYS)
    recs["suppressed_count"] = len(recs.pop("suppressed", []))

    bundle = {
        "week_from": week_from,
        "week_to": week_to,
        "cost_by_lob": _strip(cost_equation("lob", week_from, week_to), _VERBOSE_KEYS),
        "adoption_by_lob": _strip(adoption("lob", week_from, week_to), _VERBOSE_KEYS),
        "adoption_by_tool": _strip(
            _last_week_only(adoption("tool", week_from, week_to)), _VERBOSE_KEYS
        ),
        "quadrant_lob_agent": _strip(
            classify_batch(None, None, week_from or 1, week_to or 12, layer="L1_managed_agent"),
            _VERBOSE_KEYS,
        ),
        "quadrant_by_tool": _strip(
            {"results": [
                r for r in classify_batch(None, None, week_from or 1, week_to or 12)["results"]
                if r["lob_id"] is None
            ]},
            _VERBOSE_KEYS,
        ),
        "recommendations": recs,
        "anti_patterns": _strip(detect("tool", week_from, week_to), _VERBOSE_KEYS),
    }
    grounded_in = [
        "cost:lob", "adoption:lob", "adoption:tool",
        "quadrant:layer=L1_managed_agent", "quadrant:tool",
        "recommendations", "anti-patterns:tool",
    ]
    return bundle, grounded_in


# --- model call -------------------------------------------------------

def _history_messages(conversation_history: list[Any]) -> list[dict[str, str]]:
    msgs = [
        {"role": m.role, "content": m.content}
        for m in conversation_history[-MAX_HISTORY_MESSAGES:]
    ]
    # a valid conversation starts with a user turn
    while msgs and msgs[0]["role"] != "user":
        msgs.pop(0)
    return msgs


def answer_question(
    question: str,
    week_from: int | None,
    week_to: int | None,
    conversation_history: list[Any],
    *,
    client: Any | None = None,
) -> dict[str, Any]:
    bundle, grounded_in = build_context(week_from, week_to)
    client = client or anthropic.Anthropic()  # reads ANTHROPIC_API_KEY

    user_turn = (
        "Current TokenLedger data (JSON). Answer using only this data:\n\n"
        f"```json\n{json.dumps(bundle, separators=(',', ':'))}\n```\n\n"
        f"Question: {question}"
    )
    messages = _history_messages(conversation_history) + [
        {"role": "user", "content": user_turn}
    ]

    resp = client.messages.create(
        model=CHAT_MODEL,
        max_tokens=CHAT_MAX_TOKENS,
        system=SYSTEM_PROMPT,
        messages=messages,
    )
    answer = "".join(
        b.text for b in resp.content if getattr(b, "type", None) == "text"
    ).strip()
    return {"answer": answer, "grounded_in": grounded_in}


def is_configured() -> bool:
    return bool(os.environ.get("ANTHROPIC_API_KEY"))
