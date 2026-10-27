"""Snapshot bridging and live diff-depth continuity.

The bridge follows the current Spot rules:

1. If the snapshot ``lastUpdateId`` is strictly less than the first
   buffered event's ``U``, the snapshot is too old and must be retried.
2. Buffered depth events with ``u <= lastUpdateId`` are obsolete and are
   not emitted.
3. The first remaining depth event must satisfy ``U <= lastUpdateId + 1``.
   A larger ``U`` is a gap: the buffer is discarded and synchronization
   restarts. Overlap (``U <= lastUpdateId``) and the contiguous case
   (``U == lastUpdateId + 1``) are both accepted.
4. Later events use the order-book rules. A gap invalidates the book.
   Events after that gap stay buffered until a new snapshot bridges them.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Optional, Sequence, Union

from .orderbook import ApplyStatus, OrderBook, OrderBookError

MAX_BUFFER_DEFAULT = 8192


class SyncError(Exception):
    pass


class BufferOverflowError(SyncError):
    pass


@dataclass
class DepthMsg:
    U: int
    u: int
    bids: list[tuple[str, str]]
    asks: list[tuple[str, str]]
    recv_ns: int
    event_time: Optional[int] = None
    symbol: Optional[str] = None
    applied_ns: Optional[int] = None


@dataclass
class TradeMsg:
    agg_id: int
    price: str
    qty: str
    recv_ns: int
    event_time: Optional[int] = None
    trade_time: Optional[int] = None
    buyer_is_maker: Optional[bool] = None
    applied_ns: Optional[int] = None


Event = Union[DepthMsg, TradeMsg]


def partition_for_bridge(
    events: Sequence[Event],
    last_update_id: int,
    first_u: Optional[int],
) -> tuple[str, list[Event]]:
    """Classify a buffered batch against a snapshot.

    Returns ``(status, kept)`` where status is ``retry_snapshot``,
    ``wait``, ``gap``, or ``ok``. ``kept`` is non-empty only for ``ok``.
    """
    if first_u is not None and last_update_id < first_u:
        return "retry_snapshot", []

    kept: list[Event] = []
    for event in events:
        if isinstance(event, DepthMsg) and event.u <= last_update_id:
            continue
        kept.append(event)

    first_depth = next((event for event in kept if isinstance(event, DepthMsg)), None)
    if first_depth is None:
        return "wait", []
    if first_depth.U > last_update_id + 1:
        return "gap", []
    return "ok", kept


def depth_record(event: DepthMsg) -> dict:
    record = {
        "type": "depth",
        "U": event.U,
        "u": event.u,
        "b": [list(level) for level in event.bids],
        "a": [list(level) for level in event.asks],
        "E": event.event_time,
        "local_recv_ns": event.recv_ns,
    }
    if event.symbol is not None:
        record["s"] = event.symbol
    if event.applied_ns is not None:
        record["local_applied_ns"] = event.applied_ns
    return record


def trade_record(event: TradeMsg) -> dict:
    record = {
        "type": "agg_trade",
        "a": event.agg_id,
        "p": event.price,
        "q": event.qty,
        "E": event.event_time,
        "T": event.trade_time,
        "m": event.buyer_is_maker,
        "local_recv_ns": event.recv_ns,
    }
    if event.applied_ns is not None:
        record["local_applied_ns"] = event.applied_ns
    return record


def snapshot_record(
    last_update_id: int,
    bids: Sequence[Sequence[str]],
    asks: Sequence[Sequence[str]],
    recv_ns: int,
    reason: str,
    applied_ns: Optional[int] = None,
) -> dict:
    record = {
        "type": "snapshot",
        "last_update_id": last_update_id,
        "bids": [list(level[:2]) for level in bids],
        "asks": [list(level[:2]) for level in asks],
        "local_recv_ns": recv_ns,
        "reason": reason,
    }
    if applied_ns is not None:
        record["local_applied_ns"] = applied_ns
    return record


@dataclass
class SyncSession:
    max_buffer: int = MAX_BUFFER_DEFAULT
    book: OrderBook = field(default_factory=OrderBook)
    mode: str = "buffering"
    buffer: list[Event] = field(default_factory=list)
    first_u: Optional[int] = None
    out: list[dict] = field(default_factory=list)
    resyncs: int = 0
    reason: str = "initial"
    clock: Optional[Callable[[], int]] = None

    def _touch(self, event: Event) -> None:
        if self.clock is not None:
            event.applied_ns = self.clock()

    def push(self, event: Event) -> None:
        if self.mode == "buffering":
            if len(self.buffer) >= self.max_buffer:
                raise BufferOverflowError(
                    f"depth buffer exceeded {self.max_buffer} events; capture invalidated"
                )
            if isinstance(event, DepthMsg) and self.first_u is None:
                self.first_u = event.U
            self.buffer.append(event)
            return
        self._live(event)

    def accept_snapshot(
        self,
        last_update_id: int,
        bids: Sequence[Sequence[str]],
        asks: Sequence[Sequence[str]],
        recv_ns: int,
        applied_ns: Optional[int] = None,
    ) -> str:
        """Apply a REST snapshot to the current buffer.

        Returns ``ok``, ``wait``, ``retry_snapshot``, or ``gap``.
        Only ``ok`` publishes a snapshot record. A later gap while
        applying the bridged batch still returns ``ok`` because the
        snapshot was valid and the gap is recorded explicitly.
        """
        if self.mode != "buffering":
            raise SyncError("snapshot accepted while the book was live")
        status, kept = partition_for_bridge(self.buffer, last_update_id, self.first_u)
        if status == "retry_snapshot":
            return status
        if status == "wait":
            self.buffer = [
                event
                for event in self.buffer
                if not (isinstance(event, DepthMsg) and event.u <= last_update_id)
            ]
            return status
        if status == "gap":
            self.buffer.clear()
            self.first_u = None
            self.resyncs += 1
            self.reason = "resync"
            return status

        self.book.apply_snapshot(last_update_id, bids, asks)
        self.out.append(
            snapshot_record(last_update_id, bids, asks, recv_ns, self.reason, applied_ns)
        )
        self.buffer.clear()
        self.first_u = None
        self.mode = "live"
        self.reason = "resync"
        for index, event in enumerate(kept):
            self._live(event)
            if self.mode == "buffering":
                for rest in kept[index + 1 :]:
                    self.push(rest)
                break
        return "ok"

    def _live(self, event: Event) -> None:
        self._touch(event)
        if isinstance(event, TradeMsg):
            self.out.append(trade_record(event))
            return
        try:
            self.book.apply_depth(event.U, event.u, event.bids, event.asks)
        except OrderBookError:
            self.out.append(depth_record(event))
            self.mode = "buffering"
            self.buffer = []
            self.first_u = None
            self.resyncs += 1
            self.reason = "resync"
            return
        self.out.append(depth_record(event))
