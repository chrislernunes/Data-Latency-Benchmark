"""Snapshot bridging without a network."""

import pytest

from src.python.orderbook import OrderBookError
from src.python.sync_logic import (
    BufferOverflowError,
    DepthMsg,
    SyncSession,
    TradeMsg,
    partition_for_bridge,
)


def depth(first, final, bids=None, asks=None, recv_ns=1):
    return DepthMsg(U=first, u=final, bids=bids or [], asks=asks or [], recv_ns=recv_ns)


def test_bridge_statuses():
    events = [depth(50, 80, recv_ns=1), depth(90, 110, [("10", "1")], recv_ns=2)]
    status, kept = partition_for_bridge(events, 100, 50)
    assert status == "ok"
    assert [event.recv_ns for event in kept] == [2]

    status, _kept = partition_for_bridge(events, 40, 50)
    assert status == "retry_snapshot"

    status, _kept = partition_for_bridge([depth(90, 95)], 100, 90)
    assert status == "wait"

    status, _kept = partition_for_bridge([depth(103, 104)], 100, 103)
    assert status == "retry_snapshot"

    status, _kept = partition_for_bridge([depth(90, 95), depth(103, 104)], 100, 90)
    assert status == "gap"

    status, kept = partition_for_bridge(
        [depth(100, 100, recv_ns=1), depth(101, 102, recv_ns=7)],
        100,
        100,
    )
    assert status == "ok"
    assert kept[0].recv_ns == 7


def test_overlap_bridge_preserves_receive_timestamp_and_orders_levels():
    session = SyncSession(clock=lambda: 999)
    session.push(depth(98, 104, [("100.00", "1.5"), ("9", "2")], [("20", "3"), ("100", "4")], recv_ns=42))
    session.push(TradeMsg(agg_id=1, price="1", qty="1", recv_ns=43))
    assert session.accept_snapshot(100, [["101", "1"]], [["102", "1"]], recv_ns=50, applied_ns=80) == "ok"
    assert session.book.synchronized
    assert session.out[0]["type"] == "snapshot"
    depth_record = session.out[1]
    assert depth_record["local_recv_ns"] == 42
    assert depth_record["local_applied_ns"] == 999
    assert session.out[2]["type"] == "agg_trade"
    bids, asks = session.book.top_n(5)
    assert [price for price, _qty in bids] == ["101", "100", "9"]
    assert [price for price, _qty in asks] == ["20", "100", "102"]


def test_live_gap_buffers_the_following_event_until_a_new_snapshot():
    session = SyncSession()
    session.push(depth(100, 101))
    assert session.accept_snapshot(100, [["10", "1"]], [["11", "1"]], 1) == "ok"
    session.push(depth(103, 103, [("10", "9")]))  # 103 > 101 + 1
    assert session.book.synchronized is False
    assert session.mode == "buffering"
    following = depth(103, 104, [("12", "1")])
    session.push(following)
    assert session.buffer == [following]
    assert session.accept_snapshot(103, [["12", "4"]], [], 2) == "ok"
    assert session.book.synchronized
    bids, _asks = session.book.top_n(5)
    assert bids == [("12", "1")]
    assert session.resyncs == 1


def test_buffer_overflow_is_explicit():
    session = SyncSession(max_buffer=1)
    session.push(depth(1, 1))
    with pytest.raises(BufferOverflowError):
        session.push(depth(2, 2))


def test_bad_snapshot_does_not_mark_the_session_live():
    session = SyncSession()
    session.push(depth(1, 2))
    with pytest.raises(OrderBookError):
        session.accept_snapshot(1, [["nope", "1"]], [], 1)
    assert session.mode == "buffering"
    assert session.out == []
