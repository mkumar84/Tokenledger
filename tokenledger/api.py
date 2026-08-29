"""TokenLedger backend API (brief §6).

    GET /cost?group_by=lob|tool|lob_tool&week_from=&week_to=
    GET /cost/drivers?group_by=...&a_from=&a_to=&b_from=&b_to=
    GET /adoption?group_by=lob|tool|lob_tool&week_from=&week_to=
    GET /anti-patterns?group_by=lob|tool&week_from=&week_to=
    GET /recommendations?week_from=&week_to=
    GET /quadrant?lob_id=&tool_id=&week_from=&week_to=

Read-only. Synthetic data only. This is the API contract that gets locked
before the Lovable frontend build.
"""
from __future__ import annotations

from typing import Literal

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from . import __version__
from .config import cors_origins
from .engines import (
    adoption,
    classify,
    cost_equation,
    detect,
    driver_decomposition,
    recommend,
)
from .engines.quadrant import classify_batch
from .loader import load_manifest, load_sessions

app = FastAPI(
    title="TokenLedger — Tokenomics & Adoption FinOps Copilot",
    version=__version__,
    description="Backend engines for Northbridge Financial Group (synthetic data).",
)

# Browser CORS. Origins come from TOKENLEDGER_CORS_ORIGINS (comma-separated) at
# deploy time; defaults to localhost dev origins only. See config.cors_origins.
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins(),
    allow_methods=["GET", "OPTIONS"],
    allow_headers=["*"],
    allow_credentials=False,
)

GroupBy = Literal["lob", "tool", "lob_tool"]
AntiGroupBy = Literal["lob", "tool"]


@app.get("/health")
def health() -> dict:
    sessions = load_sessions()
    m = load_manifest()
    return {
        "status": "ok",
        "version": __version__,
        "sessions_loaded": len(sessions),
        "weeks": list(m.weeks),
        "lobs": m.lobs,
        "tools": sorted(m.tool_registry),
        # taxonomy the frontend needs to build the "LOB x Agent" chart axes and
        # tell managed agents apart from interactive tools
        "tool_categories": {t: meta.get("category") for t, meta in m.tool_registry.items()},
        "lob_managed_agents": m.lob_managed_agents,
        "cors_allowed_origins": cors_origins(),
    }


@app.get("/")
def root() -> dict:
    return {
        "service": "tokenledger",
        "version": __version__,
        "endpoints": [
            "/cost", "/cost/drivers", "/adoption", "/anti-patterns",
            "/recommendations", "/quadrant", "/health",
        ],
    }


def _err(fn, /, **kw):
    try:
        return fn(**kw)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e


@app.get("/cost")
def cost_endpoint(
    group_by: GroupBy = "lob",
    week_from: int | None = Query(None, ge=1),
    week_to: int | None = Query(None, ge=1),
) -> dict:
    return _err(cost_equation, group_by=group_by, week_from=week_from, week_to=week_to)


@app.get("/cost/drivers")
def cost_drivers_endpoint(
    group_by: GroupBy = "lob",
    a_from: int = Query(..., ge=1),
    a_to: int = Query(..., ge=1),
    b_from: int = Query(..., ge=1),
    b_to: int = Query(..., ge=1),
) -> dict:
    return _err(
        driver_decomposition,
        group_by=group_by,
        period_a=(a_from, a_to),
        period_b=(b_from, b_to),
    )


@app.get("/adoption")
def adoption_endpoint(
    group_by: GroupBy = "lob",
    week_from: int | None = Query(None, ge=1),
    week_to: int | None = Query(None, ge=1),
) -> dict:
    return _err(adoption, group_by=group_by, week_from=week_from, week_to=week_to)


@app.get("/anti-patterns")
def anti_patterns_endpoint(
    group_by: AntiGroupBy = "lob",
    week_from: int | None = Query(None, ge=1),
    week_to: int | None = Query(None, ge=1),
) -> dict:
    return _err(detect, group_by=group_by, week_from=week_from, week_to=week_to)


@app.get("/recommendations")
def recommendations_endpoint(
    week_from: int | None = Query(None, ge=1),
    week_to: int | None = Query(None, ge=1),
) -> dict:
    return _err(recommend, week_from=week_from, week_to=week_to)


def _csv(val: str | None) -> list[str] | None:
    if val is None:
        return None
    items = [x.strip() for x in val.split(",") if x.strip()]
    return items or None


Layer = Literal[
    "L1_managed_agent", "L2_team_skill", "L3_interactive_harness", "L4_adhoc"
]


@app.get("/quadrant")
def quadrant_endpoint(
    lob_id: str | None = None,
    tool_id: str | None = None,
    lob_ids: str | None = Query(None, description="comma-separated; batch mode"),
    tool_ids: str | None = Query(None, description="comma-separated; batch mode"),
    layer: Layer | None = Query(
        None,
        description="scope to one session layer; use L1_managed_agent for the "
                    "Group Overview 'LOB x Agent' chart so it is not blended "
                    "with interactive-tool usage",
    ),
    week_from: int = Query(..., ge=1),
    week_to: int = Query(..., ge=1),
) -> dict:
    lids = _csv(lob_ids)
    tids = _csv(tool_ids)

    # Single-slice mode (unchanged contract): a singular lob_id/tool_id and no
    # plural list params -> flat object response.
    if lids is None and tids is None and (lob_id is not None or tool_id is not None):
        return classify(lob_id, tool_id, week_from, week_to, layer=layer)

    # Batch mode: bare /quadrant -> every LOB, every tool, every populated cell;
    # explicit lists -> just those (cross product when both lists are given).
    return classify_batch(lids, tids, week_from, week_to, layer=layer)
