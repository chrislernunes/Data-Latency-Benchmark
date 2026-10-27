"""Normalized event types and capture format helpers."""

from __future__ import annotations

import json
from dataclasses import dataclass, asdict
from decimal import Decimal
from typing import Any, List, Optional, Tuple

PriceQty = Tuple[str, str]  # decimal strings


@dataclass
class Header:
    type: str = "header"
    version: int = 1
    symbol: str = ""
    market: str = "spot"
    start_ts_ns: int = 0


@dataclass
class SnapshotEvent:
    type: str = "snapshot"
    last_update_id: int = 0
    bids: List[PriceQty] = None
    asks: List[PriceQty] = None
    local_recv_ns: int = 0
    exchange_ts: Optional[int] = None

    def __post_init__(self):
        if self.bids is None:
            self.bids = []
        if self.asks is None:
            self.asks = []


@dataclass
class DepthEvent:
    type: str = "depth"
    U: int = 0  # first update id
    u: int = 0  # final update id
    b: List[PriceQty] = None
    a: List[PriceQty] = None
    E: Optional[int] = None  # exchange event time
    local_recv_ns: int = 0

    def __post_init__(self):
        if self.b is None:
            self.b = []
        if self.a is None:
            self.a = []


@dataclass
class AggTradeEvent:
    type: str = "agg_trade"
    a: int = 0  # aggregate trade id
    p: str = ""  # price
    q: str = ""  # quantity
    T: Optional[int] = None
    m: bool = False  # is buyer maker
    local_recv_ns: int = 0


def event_to_json(obj: Any) -> str:
    return json.dumps(asdict(obj), separators=(",", ":"))


def parse_event(line: str) -> Any:
    data = json.loads(line)
    t = data.get("type")
    if t == "header":
        return Header(**data)
    if t == "snapshot":
        return SnapshotEvent(**data)
    if t == "depth":
        return DepthEvent(**data)
    if t == "agg_trade":
        return AggTradeEvent(**data)
    raise ValueError(f"Unknown event type: {t}")
