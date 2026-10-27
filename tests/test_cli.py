"""CLI exit codes. Connectivity is not called."""

from pathlib import Path

from src.python.cli import main
from src.python.collector import write_capture

HEADER = {"type": "header", "version": 1, "symbol": "BTCUSDT", "market": "spot"}


def test_replay_missing_file_is_not_success():
    assert main(["replay", "--input", "missing.jsonl", "--engine", "python"]) == 1


def test_validate_and_replay_round_trip(tmp_path: Path):
    path = tmp_path / "book.jsonl"
    write_capture(
        path,
        HEADER,
        [
            {
                "type": "snapshot",
                "last_update_id": 1,
                "bids": [["2", "1"]],
                "asks": [["3", "1"]],
                "local_recv_ns": 1,
                "reason": "initial",
            }
        ],
        0,
    )
    assert main(["validate", "--input", str(path)]) == 0
    assert main(["replay", "--input", str(path), "--engine", "python"]) == 0


def test_cpp_engine_without_a_binary_fails(tmp_path: Path):
    path = tmp_path / "book.jsonl"
    write_capture(
        path,
        HEADER,
        [{"type": "snapshot", "last_update_id": 1, "bids": [], "asks": [], "local_recv_ns": 1, "reason": "initial"}],
        0,
    )
    code = main(["replay", "--input", str(path), "--engine", "cpp", "--cpp-bin", str(tmp_path / "missing-bin")])
    assert code == 1


def test_validate_rejects_tampered_hash(tmp_path: Path):
    path = tmp_path / "book.jsonl"
    write_capture(
        path,
        HEADER,
        [{"type": "snapshot", "last_update_id": 1, "bids": [["2", "1"]], "asks": [], "local_recv_ns": 1, "reason": "initial"}],
        0,
    )
    lines = path.read_text(encoding="utf-8").splitlines()
    lines[1] = lines[1].replace("2", "4", 1)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    assert main(["validate", "--input", str(path)]) == 1
