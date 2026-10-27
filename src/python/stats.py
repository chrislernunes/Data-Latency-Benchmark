"""Latency statistics.

Percentiles use linear interpolation on the sorted sample:

    rank = (pct / 100) * (n - 1)

with the value taken between the surrounding points. This is the same
definition in the C++ replay tool. An empty sample has no percentile.
"""

from __future__ import annotations

from typing import Optional, Sequence

STAT_KEYS = ("count", "min", "mean", "p50", "p90", "p95", "p99", "p99_9", "max")


def percentile(values: Sequence[int], pct: float) -> Optional[float]:
    """Linear-interpolation percentile. ``pct`` is in [0, 100]."""
    if isinstance(pct, bool) or not isinstance(pct, (int, float)):
        raise ValueError("pct must be a number between 0 and 100")
    if pct < 0 or pct > 100:
        raise ValueError("pct must be between 0 and 100")
    if not values:
        return None
    ordered = sorted(values)
    count = len(ordered)
    if count == 1:
        return float(ordered[0])
    rank = (float(pct) / 100.0) * (count - 1)
    low = int(rank)
    high = min(low + 1, count - 1)
    frac = rank - low
    return ordered[low] * (1.0 - frac) + ordered[high] * frac


def latency_stats(values: Sequence[int]) -> dict:
    """Summarize a latency sample. Empty input yields count 0 and nulls."""
    if not values:
        return {
            "count": 0,
            "min": None,
            "mean": None,
            "p50": None,
            "p90": None,
            "p95": None,
            "p99": None,
            "p99_9": None,
            "max": None,
        }
    return {
        "count": len(values),
        "min": min(values),
        "mean": sum(values) / len(values),
        "p50": percentile(values, 50),
        "p90": percentile(values, 90),
        "p95": percentile(values, 95),
        "p99": percentile(values, 99),
        "p99_9": percentile(values, 99.9),
        "max": max(values),
    }


def throughput_per_s(successful_events: int, elapsed_ns: int) -> Optional[float]:
    """Wall-clock throughput: successful events / elapsed seconds.

    This is not the reciprocal of mean service time.
    """
    if elapsed_ns < 0:
        raise ValueError("elapsed_ns must be >= 0")
    if successful_events < 0:
        raise ValueError("successful_events must be >= 0")
    if elapsed_ns == 0:
        return None
    return successful_events / (elapsed_ns / 1_000_000_000)
