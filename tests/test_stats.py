"""Percentile and throughput definitions."""

import pytest

from src.python.stats import latency_stats, percentile, throughput_per_s


def test_percentile_empty_and_single():
    assert percentile([], 50) is None
    assert percentile([7], 99.9) == 7.0
    empty = latency_stats([])
    assert empty["count"] == 0
    assert empty["p99_9"] is None
    assert empty["min"] is None


def test_percentile_endpoints_and_interpolation():
    values = [10, 20, 30, 40]
    assert percentile(values, 0) == 10
    assert percentile(values, 100) == 40
    assert percentile(values, 50) == pytest.approx(25)
    stats = latency_stats(values)
    assert stats["count"] == 4
    assert stats["min"] == 10
    assert stats["max"] == 40
    assert stats["mean"] == 25


def test_percentile_rejects_bad_inputs():
    with pytest.raises(ValueError):
        percentile([1], -0.1)
    with pytest.raises(ValueError):
        percentile([1], 100.1)
    with pytest.raises(ValueError):
        percentile([1], True)  # type: ignore[arg-type]


def test_throughput_uses_wall_clock_not_mean_service_time():
    assert throughput_per_s(0, 1_000_000_000) == 0
    assert throughput_per_s(10, 2_000_000_000) == pytest.approx(5)
    assert throughput_per_s(10, 0) is None
    with pytest.raises(ValueError):
        throughput_per_s(-1, 10)
