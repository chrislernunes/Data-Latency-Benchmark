"""Collector loop tests with a fake socket. No Binance calls."""

import asyncio
import json

import pytest

from src.python.collector import (
    CollectorError,
    capture_from_socket,
    parse_ws_payload,
    validate_request,
)


class FakeSocket:
    def __init__(self, messages):
        self.messages = list(messages)
        self.active = 0
        self.max_active = 0

    async def recv(self):
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        await asyncio.sleep(0)
        self.active -= 1
        if not self.messages:
            await asyncio.Event().wait()
        return self.messages.pop(0)


def depth_message(first, final, bids=None, asks=None):
    return json.dumps(
        {
            "e": "depthUpdate",
            "E": 1,
            "s": "BTCUSDT",
            "U": first,
            "u": final,
            "b": bids or [],
            "a": asks or [],
        }
    )


def test_combined_stream_unwraps_and_rejects_bad_levels():
    raw = json.dumps(
        {
            "stream": "btcusdt@depth",
            "data": {
                "e": "depthUpdate",
                "E": 5,
                "s": "BTCUSDT",
                "U": 1,
                "u": 2,
                "b": [["10", "1"]],
                "a": [],
            },
        }
    )
    event = parse_ws_payload(raw, 123, "BTCUSDT")
    assert event.recv_ns == 123
    assert event.U == 1
    with pytest.raises(CollectorError):
        parse_ws_payload(json.dumps({"e": "depthUpdate", "U": 1, "u": 1, "b": [[1, "1"]], "a": []}), 1, "BTCUSDT")


def test_request_validation():
    assert validate_request("BTCUSDT", 1, None, 5000, 1000) == "btcusdt@depth"
    with pytest.raises(CollectorError):
        validate_request("btcusdt", 1, None, 5000, 1000)
    with pytest.raises(CollectorError):
        validate_request("BTCUSDT", 0, None, 5000, 1000)
    with pytest.raises(CollectorError):
        validate_request("BTCUSDT", 1, 0, 5000, 1000)


def test_single_reader_preserves_timestamp_and_bridges():
    clock_values = []

    def clock():
        clock_values.append(len(clock_values) + 1)
        return clock_values[-1] * 1000

    socket = FakeSocket(
        [
            depth_message(100, 110, [["10.00", "2.0"]], [["11", "1"]]),
            depth_message(111, 111, [["10.00", "0"]]),
        ]
    )

    async def fetch():
        await asyncio.sleep(0)
        return {"lastUpdateId": 105, "bids": [["10.00", "1.0"]], "asks": [["11", "1.0"]]}, 50

    async def scenario():
        return await capture_from_socket(
            socket,
            fetch,
            symbol="BTCUSDT",
            duration_s=2,
            max_events=2,
            max_queue=8,
            clock=clock,
            sleep=_no_sleep,
        )

    session = asyncio.run(scenario())
    assert socket.max_active == 1
    assert session.book.synchronized
    depth_records = [record for record in session.out if record["type"] == "depth"]
    assert depth_records[0]["local_recv_ns"] == 1000
    assert depth_records[0]["local_applied_ns"] != depth_records[0]["local_recv_ns"]
    bids, _asks = session.book.top_n(5)
    assert bids == []


async def _no_sleep(_seconds):
    return None


def test_rest_failure_is_not_replaced_with_synthetic_data():
    socket = FakeSocket([depth_message(1, 2, [["10", "1"]], [])])

    async def fetch():
        raise CollectorError("REST GET /api/v3/depth failed: HTTP 451 body='unavailable'")

    async def scenario():
        await capture_from_socket(
            socket,
            fetch,
            symbol="BTCUSDT",
            duration_s=1,
            max_events=None,
            clock=lambda: 1,
            sleep=_no_sleep,
        )

    with pytest.raises(CollectorError, match="451"):
        asyncio.run(scenario())
