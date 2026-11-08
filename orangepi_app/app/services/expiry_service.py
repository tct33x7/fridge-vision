from __future__ import annotations

from typing import Any


def summarize_expiry(batches: list[dict[str, Any]]) -> dict[str, int]:
    states = {"fresh": 0, "expiring": 0, "expired": 0, "unknown": 0}
    for batch in batches:
        state = str(batch.get("expiry_status") or "unknown")
        if state in states:
            states[state] += 1
    return states

