"""Replay a JSONL capture through the Python order book.

Timers use ``time.perf_counter_ns`` and never mix clocks from the capture.

- ``decode_ns``: ``parse_line`` only.
- ``snapshot_update_ns``: successful ``apply_snapshot`` only.
- ``depth_update_ns``: successful depth applies only. Stale, gapped, and
  rejected events are excluded.
- ``topn_ns``: ``top_n`` after a successful snapshot or depth apply.
- ``event_processing_ns``: decode + update + top-N for those successful
  book updates. File reads are outside this interval.
- ``elapsed_ns``: wall clock around the whole replay loop, including
  file reads and rejected records.
- ``throughput_events_per_s``: successful snapshot and depth applies
  divided by ``elapsed_ns``. Not the reciprocal of mean service time.

``local_recv_ns`` from the capture is not a replay timer. Exchange
timestamps are not subtracted from local clocks.
"""

from __future__ import annotations

import time
from pathlib import Path

from .models import CaptureFormatError, UnsupportedSchemaError, levels_of, parse_line
from .orderbook import ApplyStatus, OrderBook, OrderBookError
from .stats import latency_stats, throughput_per_s


def replay_capture(path: Path | str, top_n: int = 5) -> dict:
    source = Path(path)
    if not source.is_file():
        raise FileNotFoundError(f"capture not found: {source}")
    if isinstance(top_n, bool) or not isinstance(top_n, int) or top_n < 0:
        raise ValueError("top_n must be a non-negative integer")

    book = OrderBook()
    decode_samples: list[int] = []
    snapshot_samples: list[int] = []
    depth_samples: list[int] = []
    top_samples: list[int] = []
    event_samples: list[int] = []
    checkpoints: list[dict] = []

    snapshots_applied = 0
    depth_applied = 0
    ignored_stale = 0
    gaps = 0
    invalid_records = 0
    rejected_unsynchronized = 0
    agg_trades = 0
    saw_header = False
    saw_footer = False

    def checkpoint(line_no: int) -> None:
        bids, asks = book.top_n(top_n)
        checkpoints.append(
            {
                "i": line_no,
                "synchronized": book.synchronized,
                "bids": [[price, qty] for price, qty in bids],
                "asks": [[price, qty] for price, qty in asks],
            }
        )

    wall_start = time.perf_counter_ns()
    with source.open("r", encoding="utf-8") as handle:
        for line_no, raw in enumerate(handle):
            line = raw.rstrip("\r\n")
            if line.strip() == "":
                continue
            decode_start = time.perf_counter_ns()
            try:
                record = parse_line(line)
            except UnsupportedSchemaError:
                raise
            except CaptureFormatError:
                invalid_records += 1
                book.invalidate()
                checkpoint(line_no)
                continue
            decode_ns = time.perf_counter_ns() - decode_start
            decode_samples.append(decode_ns)
            kind = record["type"]

            if not saw_header:
                if kind != "header":
                    raise CaptureFormatError("first record must be a versioned header")
                saw_header = True
                continue
            if kind == "header":
                raise CaptureFormatError("duplicate header")
            if saw_footer:
                raise CaptureFormatError("records after footer")
            if kind == "footer":
                if record.get("status") != "complete":
                    raise CaptureFormatError(
                        f"capture status is {record.get('status')!r}, expected 'complete'"
                    )
                saw_footer = True
                continue
            if kind == "snapshot":
                update_start = time.perf_counter_ns()
                try:
                    book.apply_snapshot(
                        record["last_update_id"],
                        levels_of(record, "bids"),
                        levels_of(record, "asks"),
                    )
                except OrderBookError:
                    invalid_records += 1
                    book.invalidate()
                else:
                    update_ns = time.perf_counter_ns() - update_start
                    top_start = time.perf_counter_ns()
                    book.top_n(top_n)
                    top_ns = time.perf_counter_ns() - top_start
                    snapshots_applied += 1
                    snapshot_samples.append(update_ns)
                    top_samples.append(top_ns)
                    event_samples.append(decode_ns + update_ns + top_ns)
                checkpoint(line_no)
                continue
            if kind == "depth":
                update_start = time.perf_counter_ns()
                try:
                    status = book.apply_depth(
                        record["U"],
                        record["u"],
                        levels_of(record, "b"),
                        levels_of(record, "a"),
                    )
                except OrderBookError as exc:
                    if exc.code == "gap":
                        gaps += 1
                    elif exc.code == "unsynchronized":
                        rejected_unsynchronized += 1
                    else:
                        invalid_records += 1
                else:
                    if status is ApplyStatus.IGNORED_STALE:
                        ignored_stale += 1
                    else:
                        update_ns = time.perf_counter_ns() - update_start
                        top_start = time.perf_counter_ns()
                        book.top_n(top_n)
                        top_ns = time.perf_counter_ns() - top_start
                        depth_applied += 1
                        depth_samples.append(update_ns)
                        top_samples.append(top_ns)
                        event_samples.append(decode_ns + update_ns + top_ns)
                checkpoint(line_no)
                continue
            if kind == "agg_trade":
                agg_trades += 1
                continue
            invalid_records += 1
            book.invalidate()
            checkpoint(line_no)

    if not saw_header:
        raise CaptureFormatError(f"capture has no header: {source}")
    elapsed_ns = time.perf_counter_ns() - wall_start
    successful = snapshots_applied + depth_applied
    final_bids, final_asks = book.top_n(top_n)
    return {
        "engine": "python",
        "snapshots_applied": snapshots_applied,
        "depth_applied": depth_applied,
        "ignored_stale": ignored_stale,
        "gaps": gaps,
        "invalid_records": invalid_records,
        "rejected_unsynchronized": rejected_unsynchronized,
        "agg_trades": agg_trades,
        "processed_successfully": successful,
        "synchronized": book.synchronized,
        "elapsed_ns": elapsed_ns,
        "throughput_events_per_s": throughput_per_s(successful, elapsed_ns),
        "decode_ns": latency_stats(decode_samples),
        "snapshot_update_ns": latency_stats(snapshot_samples),
        "depth_update_ns": latency_stats(depth_samples),
        "topn_ns": latency_stats(top_samples),
        "event_processing_ns": latency_stats(event_samples),
        "final_top": {
            "bids": [[price, qty] for price, qty in final_bids],
            "asks": [[price, qty] for price, qty in final_asks],
        },
        "checkpoints": checkpoints,
    }


def parity_view(result: dict) -> dict:
    """Fields that must match across engines. Timers are excluded."""
    return {
        "snapshots_applied": result["snapshots_applied"],
        "depth_applied": result["depth_applied"],
        "ignored_stale": result["ignored_stale"],
        "gaps": result["gaps"],
        "invalid_records": result["invalid_records"],
        "rejected_unsynchronized": result["rejected_unsynchronized"],
        "agg_trades": result["agg_trades"],
        "processed_successfully": result["processed_successfully"],
        "synchronized": result["synchronized"],
        "final_top": result["final_top"],
        "checkpoints": result["checkpoints"],
    }


def exit_code_for(result: dict) -> int:
    """0 only when the replay ends synchronized and every record was usable.

    A repaired gap still exits 0 if a later snapshot left the book
    synchronized and no record was malformed. An unsynchronized ending,
    a malformed record, or a depth update applied with no snapshot exits 3.
    """
    if (
        result["synchronized"]
        and result["invalid_records"] == 0
        and result["rejected_unsynchronized"] == 0
    ):
        return 0
    return 3
