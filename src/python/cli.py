"""Command-line interface for capture, replay, and validation."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

from .collector import collect
from .replay import replay
from .stats import latency_stats


def main() -> None:
    parser = argparse.ArgumentParser(description="Binance market-data latency benchmark")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_cap = sub.add_parser("capture", help="Capture live Binance data")
    p_cap.add_argument("--symbol", default="BTCUSDT")
    p_cap.add_argument("--duration", type=float, default=30.0)
    p_cap.add_argument("--output", type=Path, required=True)
    p_cap.add_argument("--trades", action="store_true")
    p_cap.add_argument("--max-events", type=int, default=None)

    p_val = sub.add_parser("validate", help="Validate capture file")
    p_val.add_argument("--input", type=Path, required=True)

    p_rep = sub.add_parser("replay", help="Replay capture")
    p_rep.add_argument("--input", type=Path, required=True)
    p_rep.add_argument("--engine", default="python")

    p_conn = sub.add_parser("connectivity", help="Optional live connectivity check")
    p_conn.add_argument("--symbol", default="BTCUSDT")
    p_conn.add_argument("--timeout", type=float, default=10.0)

    args = parser.parse_args()

    if args.cmd == "capture":
        asyncio.run(collect(args.symbol, args.duration, args.output, args.trades, args.max_events))
        print(f"Capture written to {args.output}")
    elif args.cmd == "validate":
        # simple line count and parse check
        count = 0
        with args.input.open() as f:
            for line in f:
                if line.strip():
                    count += 1
                    json.loads(line)
        print(f"Valid JSONL with {count} records")
    elif args.cmd == "replay":
        result = replay(args.input, args.engine)
        stats = latency_stats(result["latencies_ns"])
        print(json.dumps({"processed": result["processed"], "gaps": result["gaps"], "stats": stats}, indent=2))
    elif args.cmd == "connectivity":
        # minimal check
        print("Connectivity check not fully implemented in this stub; implement with timeout.")
        sys.exit(0)


if __name__ == "__main__":
    main()
