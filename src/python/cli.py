"""Command line for capture, validation, replay, parity, and connectivity."""

from __future__ import annotations

import argparse
import asyncio
import json
import subprocess
import sys
from pathlib import Path

from .collector import CollectorError, check_connectivity, collect
from .models import CaptureFormatError
from .replay import exit_code_for, parity_view, replay_capture
from .validate import validate_capture


def _print_json(payload: dict) -> None:
    json.dump(payload, sys.stdout, indent=2, sort_keys=True)
    sys.stdout.write("\n")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Binance Spot market-data latency benchmark")
    sub = parser.add_subparsers(dest="cmd", required=True)

    capture = sub.add_parser("capture", help="Capture public Binance Spot depth")
    capture.add_argument("--symbol", default="BTCUSDT")
    capture.add_argument("--duration", type=float, required=True)
    capture.add_argument("--output", type=Path, required=True)
    capture.add_argument("--trades", action="store_true")
    capture.add_argument("--max-events", type=int, default=None)
    capture.add_argument("--snapshot-limit", type=int, default=5000)
    capture.add_argument("--depth-ms", type=int, default=1000, choices=(100, 1000))
    capture.add_argument("--timeout", type=float, default=10.0)

    validate = sub.add_parser("validate", help="Validate a JSONL capture")
    validate.add_argument("--input", type=Path, required=True)

    replay = sub.add_parser("replay", help="Replay a capture")
    replay.add_argument("--input", type=Path, required=True)
    replay.add_argument("--engine", required=True, choices=("python", "cpp"))
    replay.add_argument("--cpp-bin", type=Path, default=Path("build/binance_md_benchmark"))
    replay.add_argument("--top", type=int, default=5)

    compare = sub.add_parser("compare", help="Compare Python and C++ replays")
    compare.add_argument("--input", type=Path, required=True)
    compare.add_argument("--cpp-bin", type=Path, default=Path("build/binance_md_benchmark"))
    compare.add_argument("--top", type=int, default=5)

    connectivity = sub.add_parser("connectivity", help="Check public REST and WebSocket access")
    connectivity.add_argument("--symbol", default="BTCUSDT")
    connectivity.add_argument("--timeout", type=float, default=10.0)
    return parser


def _run_cpp(binary: Path, capture: Path, top: int) -> tuple[int, dict]:
    if not binary.is_file():
        raise FileNotFoundError(
            f"C++ replay binary not found at {binary}. "
            "Configure a Release build with cmake and pass --cpp-bin if needed."
        )
    completed = subprocess.run(
        [str(binary), "replay", "--input", str(capture), "--top", str(top)],
        check=False,
        capture_output=True,
        text=True,
    )
    if not completed.stdout.strip():
        detail = completed.stderr.strip() or "no stdout"
        raise RuntimeError(f"C++ replay exited {completed.returncode} without JSON: {detail}")
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"C++ replay did not print JSON: {exc}") from exc
    return completed.returncode, payload


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.cmd == "capture":
            asyncio.run(
                collect(
                    args.symbol,
                    args.duration,
                    args.output,
                    include_trades=args.trades,
                    max_events=args.max_events,
                    snapshot_limit=args.snapshot_limit,
                    depth_ms=args.depth_ms,
                    timeout=args.timeout,
                )
            )
            print(f"capture written to {args.output}")
            return 0
        if args.cmd == "validate":
            report = validate_capture(args.input)
            _print_json(
                {
                    "synchronized": report["synchronized"],
                    "snapshots_applied": report["snapshots_applied"],
                    "depth_applied": report["depth_applied"],
                    "ignored_stale": report["ignored_stale"],
                    "gaps": report["gaps"],
                    "invalid_records": report["invalid_records"],
                    "rejected_unsynchronized": report["rejected_unsynchronized"],
                    "agg_trades": report["agg_trades"],
                    "sha256_checked": report["sha256_checked"],
                }
            )
            if (
                report["synchronized"]
                and report["invalid_records"] == 0
                and report["rejected_unsynchronized"] == 0
            ):
                return 0
            return 3
        if args.cmd == "replay":
            if args.engine == "python":
                result = replay_capture(args.input, args.top)
                _print_json(result)
                return exit_code_for(result)
            code, payload = _run_cpp(args.cpp_bin, args.input, args.top)
            _print_json(payload)
            return code
        if args.cmd == "compare":
            python_result = replay_capture(args.input, args.top)
            _code, cpp_result = _run_cpp(args.cpp_bin, args.input, args.top)
            left = parity_view(python_result)
            right = parity_view(cpp_result)
            if left != right:
                _print_json({"match": False, "python": left, "cpp": right})
                return 1
            _print_json(
                {
                    "match": True,
                    "synchronized": left["synchronized"],
                    "processed_successfully": left["processed_successfully"],
                    "checkpoints": len(left["checkpoints"]),
                }
            )
            return 0
        if args.cmd == "connectivity":
            report = asyncio.run(check_connectivity(args.symbol, args.timeout))
            _print_json(report)
            return 0
    except (CollectorError, CaptureFormatError, FileNotFoundError, OSError, RuntimeError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except Exception as exc:
        name = type(exc).__name__
        print(f"{name}: {exc}", file=sys.stderr)
        return 1
    print(f"unsupported command: {args.cmd}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
