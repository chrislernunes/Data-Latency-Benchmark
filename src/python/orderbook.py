"""Order book with absolute quantity Level-2 semantics. String price keys for exactness."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Dict, List, Optional, Tuple


class OrderBookError(Exception):
    pass


class OrderBook:
    """
    Local order book for Binance Level-2 absolute quantity updates.

    Bids: descending price order.
    Asks: ascending price order.
    Price keys are decimal strings to avoid floating-point equality issues.
    """

    def __init__(self) -> None:
        self.bids: Dict[str, str] = {}  # price -> qty
        self.asks: Dict[str, str] = {}
        self.last_update_id: Optional[int] = None
        self.synchronized: bool = False

    def apply_snapshot(self, last_update_id: int, bids: List[Tuple[str, str]], asks: List[Tuple[str, str]]) -> None:
        self.bids.clear()
        self.asks.clear()
        for p, q in bids:
            self._set_level(self.bids, p, q)
        for p, q in asks:
            self._set_level(self.asks, p, q)
        self.last_update_id = last_update_id
        self.synchronized = True

    def apply_depth(self, U: int, u: int, bids: List[Tuple[str, str]], asks: List[Tuple[str, str]]) -> None:
        if not self.synchronized or self.last_update_id is None:
            raise OrderBookError("Book not synchronized")
        if U != self.last_update_id + 1:
            self.synchronized = False
            raise OrderBookError(f"Sequence gap: expected U={self.last_update_id + 1}, got {U}")
        for p, q in bids:
            self._set_level(self.bids, p, q)
        for p, q in asks:
            self._set_level(self.asks, p, q)
        self.last_update_id = u

    def _set_level(self, side: Dict[str, str], price: str, qty: str) -> None:
        try:
            dqty = Decimal(qty)
            if dqty < 0:
                raise OrderBookError(f"Negative quantity: {qty}")
            if dqty == 0:
                side.pop(price, None)
            else:
                side[price] = qty
        except (InvalidOperation, ValueError) as e:
            raise OrderBookError(f"Invalid price/qty: {price}/{qty}") from e

    def top_n(self, n: int = 5) -> Tuple[List[Tuple[str, str]], List[Tuple[str, str]]]:
        # Sort bids descending, asks ascending by decimal price
        def sort_key(p: str) -> Decimal:
            return Decimal(p)

        bid_items = sorted(self.bids.items(), key=lambda x: sort_key(x[0]), reverse=True)[:n]
        ask_items = sorted(self.asks.items(), key=lambda x: sort_key(x[0]))[:n]
        return bid_items, ask_items

    def is_empty_side(self, side: str) -> bool:
        if side == "bid":
            return len(self.bids) == 0
        if side == "ask":
            return len(self.asks) == 0
        raise ValueError(side)
