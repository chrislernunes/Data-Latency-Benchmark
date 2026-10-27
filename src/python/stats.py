"""Latency statistics utilities."""

from __future__ import annotations

from typing import List, Optional


def percentile(values: List[int], pct: float) -> Optional[float]:
    """Linear interpolation percentile. Returns None if empty."""
    if not values:
        return None
    sorted_vals = sorted(values)
    n = len(sorted_vals)
    if n == 1:
        return float(sorted_vals[0])
    rank = (pct / 100.0) * (n - 1)
    low = int(rank)
    high = min(low + 1, n - 1)
    frac = rank - low
    return sorted_vals[low] * (1.0 - frac) + sorted_vals[high] * frac


def latency_stats(values: List[int]) -> dict:
    if not values:
        return {"count": 0}
    return {
        "count": len(values),
        "min": min(values),
        "mean": sum(values) / len(values),
        "p50": percentile(values, 50),
        "p90": percentile(values, 90),
        "p95": percentile(values, 95),
        "p99": percentile(values, 99),
        "p999": percentile(values, 99.9),
        "max": max(values),
    }
