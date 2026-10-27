"""Test percentile calculations."""

from src.python.stats import percentile, latency_stats


def test_percentile_empty():
    assert percentile([], 50) is None


def test_percentile_single():
    assert percentile([100], 50) == 100.0


def test_percentile_basic():
    vals = [10, 20, 30, 40, 50]
    assert percentile(vals, 50) == 30.0
    stats = latency_stats(vals)
    assert stats["count"] == 5
    assert stats["min"] == 10
    assert stats["max"] == 50
