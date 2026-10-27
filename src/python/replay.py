"""Deterministic replay of capture files into order-book engines."""

from __future__ import annotations

import time
from pathlib import Path
from typing import List, Optional, Tuple

from .models import parse_event, SnapshotEvent, DepthEvent
from .orderbook import OrderBook, OrderBookError


def replay(path: Path, engine: str = "python") -> dict:
    """Replay a capture and return timing and final state."""
    book = OrderBook()
    latencies_ns: List[int] = []
    processed = 0
    gaps = 0
    invalid = 0

    with path.open() as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                ev = parse_event(line)
            except Exception:
                invalid += 1
                continue

            if isinstance(ev, SnapshotEvent):
                t0 = time.perf_counter_ns()
                book.apply_snapshot(ev.last_update_id, ev.bids, ev.asks)
                latencies_ns.append(time.perf_counter_ns() - t0)
                processed += 1
            elif isinstance(ev, DepthEvent):
                t0 = time.perf_counter_ns()
                try:
                    book.apply_depth(ev.U, ev.u, ev.b, ev.a)
                    latencies_ns.append(time.perf_counter_ns() - t0)
                    processed += 1
                except OrderBookError:
                    gaps += 1
                    book.synchronized = False
            # ignore header and trades for book update timing

    return {
        "processed": processed,
        "gaps": gaps,
        "invalid": invalid,
        "latencies_ns": latencies_ns,
        "final_top": book.top_n(5),
        "synchronized": book.synchronized,
    }
