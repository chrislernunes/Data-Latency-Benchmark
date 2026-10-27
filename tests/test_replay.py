"""Replay metrics and Python/C++ checkpoint parity."""

import json
from pathlib import Path

import pytest

from src.python.collector import write_capture
from src.python.replay import exit_code_for, parity_view, replay_capture

FIXTURES = Path(__file__).parent / "fixtures"
HEADER = {
    "type": "header",
    "version": 1,
    "symbol": "BTCUSDT",
    "market": "spot",
    "depth_stream": "btcusdt@depth",
    "include_trades": True,
    "snapshot_limit": 5000,
    "clock": "perf_counter_ns",
}


def parity_records():
    return [
        {
            "type": "snapshot",
            "last_update_id": 100,
            "bids": [["100.00", "1.50"], ["99.5", "2"], ["9", "3.0"]],
            "asks": [["101.0", "1"], ["20", "4"], ["100", "5.00"]],
            "local_recv_ns": 1,
            "reason": "initial",
        },
        {
            "type": "depth",
            "U": 100,
            "u": 104,
            "b": [["99.50", "0.00000000"], ["100", "2.0"]],
            "a": [["20.0", "0"]],
            "E": 1,
            "local_recv_ns": 2,
        },
        {
            "type": "agg_trade",
            "a": 7,
            "p": "100.1",
            "q": "0.01",
            "E": 3,
            "T": 3,
            "m": False,
            "local_recv_ns": 3,
        },
        {
            "type": "depth",
            "U": 90,
            "u": 99,
            "b": [["1", "9"]],
            "a": [],
            "E": 4,
            "local_recv_ns": 4,
        },
        {
            "type": "depth",
            "U": 105,
            "u": 106,
            "b": [["9.0", "0"]],
            "a": [["100.000", "1.0"]],
            "E": 5,
            "local_recv_ns": 5,
        },
    ]


def gap_records():
    return [
        {
            "type": "snapshot",
            "last_update_id": 10,
            "bids": [["5", "1"]],
            "asks": [["6", "1"]],
            "local_recv_ns": 1,
            "reason": "initial",
        },
        {"type": "depth", "U": 12, "u": 12, "b": [], "a": [], "E": 2, "local_recv_ns": 2},
    ]


def test_replay_separates_stages_and_canonical_top(tmp_path: Path):
    path = tmp_path / "parity.jsonl"
    write_capture(path, HEADER, parity_records(), 0)
    result = replay_capture(path)
    assert result["snapshots_applied"] == 1
    assert result["depth_applied"] == 2
    assert result["ignored_stale"] == 1
    assert result["agg_trades"] == 1
    assert result["gaps"] == 0
    assert result["invalid_records"] == 0
    assert result["synchronized"] is True
    assert result["final_top"] == {"bids": [["100", "2"]], "asks": [["100", "1"], ["101", "1"]]}
    assert result["snapshot_update_ns"]["count"] == 1
    assert result["depth_update_ns"]["count"] == 2
    assert result["topn_ns"]["count"] == 3
    assert result["processed_successfully"] == 3
    assert result["throughput_events_per_s"] == pytest.approx(
        result["processed_successfully"] / (result["elapsed_ns"] / 1e9)
    )
    assert [point["i"] for point in result["checkpoints"]] == [1, 2, 4, 5]
    assert result["checkpoints"][0]["asks"][0][0] == "20"
    assert exit_code_for(result) == 0


def test_gap_does_not_report_success(tmp_path: Path):
    path = tmp_path / "gap.jsonl"
    write_capture(path, HEADER, gap_records(), 0)
    result = replay_capture(path)
    assert result["gaps"] == 1
    assert result["synchronized"] is False
    assert result["final_top"] == {"bids": [], "asks": []}
    assert result["depth_applied"] == 0
    assert exit_code_for(result) == 3


def test_malformed_line_invalidates_and_unsupported_schema_is_fatal(tmp_path: Path):
    path = tmp_path / "bad.jsonl"
    write_capture(path, HEADER, parity_records(), 0)
    text = path.read_text(encoding="utf-8").splitlines()
    text.insert(2, "{not json")
    path.write_text("\n".join(text) + "\n", encoding="utf-8")
    result = replay_capture(path)
    assert result["invalid_records"] >= 1
    assert result["synchronized"] is False

    broken = tmp_path / "schema.jsonl"
    broken.write_text('{"type":"header","version":2,"symbol":"BTCUSDT","market":"spot"}\n', encoding="utf-8")
    with pytest.raises(Exception, match="unsupported schema version"):
        replay_capture(broken)


def test_missing_file():
    with pytest.raises(FileNotFoundError):
        replay_capture("captures/does-not-exist.jsonl")


def test_committed_fixtures_match_the_python_engine():
    parity = replay_capture(FIXTURES / "parity.jsonl")
    gap = replay_capture(FIXTURES / "gap.jsonl")
    assert parity_view(parity)["final_top"]["bids"] == [["100", "2"]]
    assert gap["synchronized"] is False
    assert json.loads((FIXTURES / "parity.jsonl").read_text(encoding="utf-8").splitlines()[-1])["status"] == "complete"
