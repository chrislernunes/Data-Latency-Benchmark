"""Unit tests for order book semantics and sequence handling."""

import pytest
from src.python.orderbook import OrderBook, OrderBookError


def test_snapshot_and_topn():
    book = OrderBook()
    book.apply_snapshot(100, [("100.0", "1.0"), ("99.0", "2.0")], [("101.0", "1.5")])
    bids, asks = book.top_n(5)
    assert bids[0][0] == "100.0"
    assert asks[0][0] == "101.0"
    assert book.synchronized


def test_zero_quantity_removal():
    book = OrderBook()
    book.apply_snapshot(100, [("100.0", "1.0")], [("101.0", "1.0")])
    book.apply_depth(101, 101, [("100.0", "0")], [])
    assert "100.0" not in book.bids


def test_sequence_gap():
    book = OrderBook()
    book.apply_snapshot(100, [], [])
    with pytest.raises(OrderBookError):
        book.apply_depth(102, 102, [], [])  # gap


def test_empty_sides():
    book = OrderBook()
    book.apply_snapshot(1, [], [])
    bids, asks = book.top_n(5)
    assert bids == []
    assert asks == []
