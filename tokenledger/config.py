"""Filesystem configuration.

File-based for this phase per the handoff brief (§3): engines read
``sessions.jsonl`` directly. Swap ``DATA_DIR`` / the loader for a real DB or
billing API later without touching engine code.
"""
from __future__ import annotations

import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# Allow override for deployment (e.g. Railway volume mount).
DATA_DIR = Path(os.environ.get("TOKENLEDGER_DATA_DIR", REPO_ROOT / "data"))

SESSIONS_PATH = DATA_DIR / "sessions.jsonl"
MANIFEST_PATH = DATA_DIR / "manifest.json"

# --- CORS ---------------------------------------------------------------
# Browser origins allowed to call the API. Defaults to local dev only; the
# deployed frontend origin(s) are supplied at deploy time (e.g. on Railway) via
# TOKENLEDGER_CORS_ORIGINS, a comma-separated list of exact origins
# ("https://foo.lovable.app,https://app.example.com"). No wildcard default.
_DEFAULT_CORS_ORIGINS = (
    "http://localhost:3000",
    "http://localhost:5173",
    "http://localhost:8080",
    "http://127.0.0.1:3000",
    "http://127.0.0.1:5173",
)


def cors_origins() -> list[str]:
    raw = os.environ.get("TOKENLEDGER_CORS_ORIGINS", "").strip()
    if not raw:
        return list(_DEFAULT_CORS_ORIGINS)
    return [o.strip() for o in raw.split(",") if o.strip()]
