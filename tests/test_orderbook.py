"""Order-book semantics shared by the Python engine."""

import pytest

from src.python.orderbook import ApplyStatus, OrderBook, OrderBookError


def test_snapshot_top_n_is_numeric_not_lexicographic():
    book = OrderBook()
    book.apply_snapshot(
        100,
        [("100.00", "1.50"), ("20", "2"), ("9", "3.0")],
        [("100", "5"), ("20.0", "4"), ("9.00", "1")],
    )
    bids, asks = book.top_n(5)
    assert [price for price, _qty in bids] == ["100", "20", "9"]
    assert [price for price, _qty in asks] == ["9", "20", "100"]
    assert bids[0][1] == "1.5"
    assert book.synchronized


def test_insert_replace_and_zero_quantity_formats():
    book = OrderBook()
    book.apply_snapshot(10, [("1.0", "1")], [("2", "1")])
    assert book.apply_depth(11, 11, [("1.50", "4"), ("1.0", "0")], [("3", "8")]) is ApplyStatus.APPLIED
    bids, asks = book.top_n(5)
    assert bids == [("1.5", "4")]
    assert asks == [("2", "1"), ("3", "8")]
    book.apply_depth(12, 12, [], [("2.0", "0.00000000")])
    _bids, asks = book.top_n(5)
    assert asks == [("3", "8")]


def test_same_numeric_price_collapses_formatting():
    book = OrderBook()
    book.apply_snapshot(1, [("99.50", "1"), ("99.5", "2.00")], [])
    bids, _asks = book.top_n(5)
    assert bids == [("99.5", "2")]


def test_reject_bad_decimals_without_publishing_a_partial_snapshot():
    book = OrderBook()
    book.apply_snapshot(1, [("10", "1")], [("11", "1")])
    for price, qty in [("", "1"), ("-1", "1"), ("nan", "1"), ("inf", "1"), ("1e-2", "1"), ("1.2.3", "1"), ("0", "1"), ("10", "-1"), ("10", "")]:
        with pytest.raises(OrderBookError) as caught:
            book.apply_snapshot(2, [(price, qty)], [])
        assert caught.value.code == "invalid_level"
        assert book.synchronized
        assert book.last_update_id == 1
        assert book.top_n(1)[0] == [("10", "1")]


def test_sequence_rules():
    book = OrderBook()
    book.apply_snapshot(100, [("10", "1")], [("11", "1")])

    assert book.apply_depth(90, 99, [("10", "9")], []) is ApplyStatus.IGNORED_STALE
    assert book.top_n(1)[0] == [("10", "1")]
    assert book.last_update_id == 100

    assert book.apply_depth(100, 100, [("10", "4")], []) is ApplyStatus.APPLIED
    assert book.last_update_id == 100
    assert book.top_n(1)[0] == [("10", "4")]

    assert book.apply_depth(99, 102, [("10", "5")], []) is ApplyStatus.APPLIED
    assert book.last_update_id == 102

    assert book.apply_depth(103, 104, [("10", "6")], []) is ApplyStatus.APPLIED
    assert book.last_update_id == 104

    with pytest.raises(OrderBookError) as gap:
        book.apply_depth(106, 107, [("10", "7")], [])
    assert gap.value.code == "gap"
    assert book.synchronized is False
    assert book.top_n(5) == ([], [])

    with pytest.raises(OrderBookError) as unsynced:
        book.apply_depth(108, 108, [], [])
    assert unsynced.value.code == "unsynchronized"
    assert book.top_n(5) == ([], [])

    book.apply_snapshot(200, [], [])
    assert book.synchronized
    assert book.top_n(5) == ([], [])


def test_malformed_ids_invalidate():
    book = OrderBook()
    book.apply_snapshot(5, [("10", "1")], [])
    with pytest.raises(OrderBookError) as caught:
        book.apply_depth(8, 7, [], [])
    assert caught.value.code == "malformed"
    assert book.synchronized is False


def test_empty_sides_and_update_before_snapshot():
    book = OrderBook()
    assert book.top_n(5) == ([], [])
    with pytest.raises(OrderBookError) as caught:
        book.apply_depth(1, 1, [("10", "1")], [])
    assert caught.value.code == "unsynchronized"
    book.apply_snapshot(1, [], [])
    bids, asks = book.top_n(3)
    assert bids == []
    assert asks == []
