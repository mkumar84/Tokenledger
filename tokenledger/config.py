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
