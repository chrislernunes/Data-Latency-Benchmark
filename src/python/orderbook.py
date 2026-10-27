"""Level-2 order book with absolute Binance quantities.

Update-id rules match the Spot diff-depth procedure:

- ``u < last_update_id``: the event is obsolete and is ignored.
- ``U > last_update_id + 1``: a sequence gap. The book is invalidated.
- otherwise the event is applied, including overlapping ranges, and
  ``last_update_id`` becomes ``u``.

A zero quantity removes the price level. Prices and quantities stay
decimal strings; keys are canonical so ``"1.0"`` and ``"1.00"`` are one
level. ``top_n`` on an unsynchronized book is empty.
"""

from __future__ import annotations

from enum import Enum
from typing import List, Optional, Sequence, Tuple

from .decimal_util import DecimalFormatError, canonical_decimal, compare_decimal, is_zero

Level = Tuple[str, str]


class OrderBookError(Exception):
    def __init__(self, message: str, code: str = "error") -> None:
        super().__init__(message)
        self.code = code


class ApplyStatus(Enum):
    APPLIED = "applied"
    IGNORED_STALE = "ignored_stale"


class OrderBook:
    def __init__(self) -> None:
        self.bids: dict[str, str] = {}
        self.asks: dict[str, str] = {}
        self.last_update_id: Optional[int] = None
        self.synchronized: bool = False

    def apply_snapshot(
        self,
        last_update_id: int,
        bids: Sequence[Sequence[str]],
        asks: Sequence[Sequence[str]],
    ) -> None:
        if isinstance(last_update_id, bool) or not isinstance(last_update_id, int):
            raise OrderBookError("snapshot last_update_id must be an integer", "invalid_level")
        if last_update_id < 0:
            raise OrderBookError("snapshot last_update_id must be >= 0", "invalid_level")
        try:
            new_bids = self._build_side(bids)
            new_asks = self._build_side(asks)
        except OrderBookError:
            raise
        self.bids = new_bids
        self.asks = new_asks
        self.last_update_id = last_update_id
        self.synchronized = True

    def apply_depth(
        self,
        first_id: int,
        final_id: int,
        bids: Sequence[Sequence[str]],
        asks: Sequence[Sequence[str]],
    ) -> ApplyStatus:
        if not self.synchronized or self.last_update_id is None:
            raise OrderBookError("book is not synchronized", "unsynchronized")
        try:
            self._check_ids(first_id, final_id)
        except OrderBookError:
            self._invalidate()
            raise
        if final_id < self.last_update_id:
            return ApplyStatus.IGNORED_STALE
        if first_id > final_id:
            self._invalidate()
            raise OrderBookError(
                f"malformed depth ids U={first_id} u={final_id}",
                "malformed",
            )
        if first_id > self.last_update_id + 1:
            self._invalidate()
            raise OrderBookError(
                f"sequence gap: book={self.last_update_id} U={first_id} u={final_id}",
                "gap",
            )
        try:
            bid_ops = self._prepare(bids)
            ask_ops = self._prepare(asks)
        except OrderBookError:
            self._invalidate()
            raise
        self._commit(self.bids, bid_ops)
        self._commit(self.asks, ask_ops)
        self.last_update_id = final_id
        return ApplyStatus.APPLIED

    def invalidate(self) -> None:
        """Drop all levels and clear synchronization."""
        self._invalidate()

    def top_n(self, n: int = 5) -> Tuple[List[Level], List[Level]]:
        if isinstance(n, bool) or not isinstance(n, int) or n < 0:
            raise OrderBookError("top n must be a non-negative integer", "invalid_level")
        if not self.synchronized:
            return [], []
        bids = sorted(self.bids.items(), key=lambda item: _sort_key(item[0]), reverse=True)[:n]
        asks = sorted(self.asks.items(), key=lambda item: _sort_key(item[0]))[:n]
        return list(bids), list(asks)

    def _invalidate(self) -> None:
        self.bids.clear()
        self.asks.clear()
        self.last_update_id = None
        self.synchronized = False

    def _build_side(self, levels: Sequence[Sequence[str]]) -> dict[str, str]:
        side: dict[str, str] = {}
        self._commit(side, self._prepare(levels))
        return side

    def _prepare(self, levels: Sequence[Sequence[str]]) -> List[Tuple[str, Optional[str]]]:
        if not isinstance(levels, (list, tuple)):
            raise OrderBookError("levels must be a list", "invalid_level")
        prepared: List[Tuple[str, Optional[str]]] = []
        for level in levels:
            if not isinstance(level, (list, tuple)) or len(level) < 2:
                raise OrderBookError("price level must have price and quantity", "invalid_level")
            try:
                price = canonical_decimal(level[0])
                qty = canonical_decimal(level[1])
            except DecimalFormatError as exc:
                raise OrderBookError(str(exc), "invalid_level") from exc
            if is_zero(price):
                raise OrderBookError("price must be positive", "invalid_level")
            prepared.append((price, None if is_zero(qty) else qty))
        return prepared

    @staticmethod
    def _commit(side: dict[str, str], ops: Sequence[Tuple[str, Optional[str]]]) -> None:
        for price, qty in ops:
            if qty is None:
                side.pop(price, None)
            else:
                side[price] = qty

    @staticmethod
    def _check_ids(first_id: int, final_id: int) -> None:
        if isinstance(first_id, bool) or not isinstance(first_id, int):
            raise OrderBookError("U must be an integer", "malformed")
        if isinstance(final_id, bool) or not isinstance(final_id, int):
            raise OrderBookError("u must be an integer", "malformed")
        if first_id < 0 or final_id < 0:
            raise OrderBookError("update ids must be >= 0", "malformed")


def _sort_key(price: str) -> tuple:
    # compare_decimal is the ordering; a wrapper key keeps sort stable.
    class _Key:
        def __init__(self, value: str) -> None:
            self.value = value

        def __lt__(self, other: "_Key") -> bool:
            return compare_decimal(self.value, other.value) < 0

    return _Key(price)
