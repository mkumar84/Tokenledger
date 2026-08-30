"""Tiny in-process sliding-window rate limiter (Backend Patch 7).

Single-instance only — state is per-process and resets on redeploy. That is
acceptable for a demo; a multi-instance deployment would need a shared store.
"""
from __future__ import annotations

import threading
import time


class SlidingWindowLimiter:
    def __init__(self, max_requests: int, window_seconds: float):
        self.max_requests = max_requests
        self.window = window_seconds
        self._hits: dict[str, list[float]] = {}
        self._lock = threading.Lock()

    def check(self, key: str, *, now: float | None = None) -> bool:
        """Record a hit for ``key``; return True if it is within the limit."""
        now = time.monotonic() if now is None else now
        with self._lock:
            recent = [t for t in self._hits.get(key, []) if now - t < self.window]
            if len(recent) >= self.max_requests:
                self._hits[key] = recent
                return False
            recent.append(now)
            self._hits[key] = recent
            return True

    def retry_after_seconds(self, key: str, *, now: float | None = None) -> int:
        now = time.monotonic() if now is None else now
        with self._lock:
            recent = sorted(t for t in self._hits.get(key, []) if now - t < self.window)
        if len(recent) < self.max_requests:
            return 0
        return max(1, int(self.window - (now - recent[0])) + 1)

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()
