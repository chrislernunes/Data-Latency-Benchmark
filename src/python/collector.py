"""Binance Spot public market-data collector.

One task owns ``ws.recv``. The receive timestamp is taken immediately
after the socket returns a message and before JSON parsing. REST
snapshots are fetched while that reader keeps buffering. There is no
synthetic feed: HTTP 451 and other transport errors abort the capture.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from pathlib import Path
from typing import Awaitable, Callable, Optional

import aiohttp
import websockets

from .models import SCHEMA_VERSION, dumps
from .sync_logic import (
    BufferOverflowError,
    DepthMsg,
    Event,
    SyncSession,
    TradeMsg,
)
from .validate import file_sha256

REST_BASE = "https://api.binance.com/api/v3"
WS_ROOT = "wss://stream.binance.com:9443"
MAX_QUEUE = 8192
MAX_BUFFER = 8192
MAX_RESYNCS = 5
MAX_SNAPSHOT_RETRIES = 5


class CollectorError(Exception):
    pass


def _log(message: str) -> None:
    print(message, file=sys.stderr)


def validate_request(
    symbol: str,
    duration_s: float,
    max_events: Optional[int],
    snapshot_limit: int,
    depth_ms: int,
) -> str:
    if not isinstance(symbol, str) or not symbol.isalnum() or not symbol.isupper():
        raise CollectorError("symbol must be an uppercase alphanumeric Spot symbol")
    if isinstance(duration_s, bool) or not isinstance(duration_s, (int, float)) or duration_s <= 0:
        raise CollectorError("duration must be a positive number of seconds")
    if duration_s > 24 * 60 * 60:
        raise CollectorError("duration must be <= 86400 seconds")
    if max_events is not None and (
        isinstance(max_events, bool) or not isinstance(max_events, int) or max_events < 1
    ):
        raise CollectorError("max_events must be a positive integer")
    if isinstance(snapshot_limit, bool) or not isinstance(snapshot_limit, int):
        raise CollectorError("snapshot_limit must be an integer from 1 to 5000")
    if snapshot_limit < 1 or snapshot_limit > 5000:
        raise CollectorError("snapshot_limit must be from 1 to 5000")
    if depth_ms not in (100, 1000):
        raise CollectorError("depth_ms must be 100 or 1000")
    stream = f"{symbol.lower()}@depth" if depth_ms == 1000 else f"{symbol.lower()}@depth@100ms"
    return stream


def stream_url(symbol: str, depth_stream: str, include_trades: bool) -> str:
    if not include_trades:
        return f"{WS_ROOT}/ws/{depth_stream}"
    trade_stream = f"{symbol.lower()}@aggTrade"
    return f"{WS_ROOT}/stream?streams={depth_stream}/{trade_stream}"


def parse_ws_payload(text: str, recv_ns: int, symbol: str) -> Event:
    if isinstance(text, bytes):
        text = text.decode("utf-8")
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise CollectorError(f"invalid JSON from websocket: {exc}") from exc
    if not isinstance(data, dict):
        raise CollectorError("websocket payload is not a JSON object")
    if "stream" in data and isinstance(data.get("data"), dict):
        data = data["data"]
    kind = data.get("e")
    if kind == "depthUpdate":
        seen = data.get("s")
        if seen is not None and seen != symbol:
            raise CollectorError(f"depth update for {seen}, expected {symbol}")
        return DepthMsg(
            U=_event_id(data, "U"),
            u=_event_id(data, "u"),
            bids=_ws_levels(data.get("b"), "b"),
            asks=_ws_levels(data.get("a"), "a"),
            recv_ns=recv_ns,
            event_time=_optional_int(data.get("E")),
            symbol=seen if isinstance(seen, str) else symbol,
        )
    if kind == "aggTrade":
        price = data.get("p")
        qty = data.get("q")
        if not isinstance(price, str) or not isinstance(qty, str):
            raise CollectorError("aggTrade price and quantity must be strings")
        maker = data.get("m")
        if maker is not None and not isinstance(maker, bool):
            raise CollectorError("aggTrade maker flag must be a boolean")
        return TradeMsg(
            agg_id=_event_id(data, "a"),
            price=price,
            qty=qty,
            recv_ns=recv_ns,
            event_time=_optional_int(data.get("E")),
            trade_time=_optional_int(data.get("T")),
            buyer_is_maker=maker if isinstance(maker, bool) else None,
        )
    raise CollectorError(f"unexpected websocket event type: {kind!r}")


def _event_id(data: dict, key: str) -> int:
    value = data.get(key)
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise CollectorError(f"websocket field {key} must be a non-negative integer")
    return value


def _optional_int(value: object) -> Optional[int]:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise CollectorError("websocket timestamp must be an integer")
    return value


def _ws_levels(value: object, key: str) -> list[tuple[str, str]]:
    if not isinstance(value, list):
        raise CollectorError(f"websocket field {key} must be a list")
    levels: list[tuple[str, str]] = []
    for level in value:
        if (
            not isinstance(level, list)
            or len(level) < 2
            or not isinstance(level[0], str)
            or not isinstance(level[1], str)
        ):
            raise CollectorError(f"websocket {key} levels must be [price, quantity] strings")
        levels.append((level[0], level[1]))
    return levels


def _snapshot_levels(value: object, key: str) -> list[list[str]]:
    if not isinstance(value, list):
        raise CollectorError(f"REST snapshot {key} must be a list")
    levels: list[list[str]] = []
    for level in value:
        if (
            not isinstance(level, list)
            or len(level) < 2
            or not isinstance(level[0], str)
            or not isinstance(level[1], str)
        ):
            raise CollectorError(f"REST snapshot {key} levels must be [price, quantity] strings")
        levels.append([level[0], level[1]])
    return levels


async def fetch_snapshot(
    session: aiohttp.ClientSession,
    symbol: str,
    limit: int,
    timeout: float,
    clock: Callable[[], int] = time.perf_counter_ns,
) -> tuple[dict, int]:
    url = f"{REST_BASE}/depth"
    try:
        async with session.get(
            url,
            params={"symbol": symbol, "limit": str(limit)},
            timeout=aiohttp.ClientTimeout(total=timeout),
        ) as response:
            body = await response.read()
            recv_ns = clock()
            if response.status != 200:
                detail = body[:400].decode("utf-8", errors="replace")
                raise CollectorError(
                    f"REST GET /api/v3/depth failed: HTTP {response.status} body={detail!r}"
                )
    except asyncio.TimeoutError as exc:
        raise CollectorError(f"REST GET /api/v3/depth timed out after {timeout}s") from exc
    except aiohttp.ClientError as exc:
        raise CollectorError(f"REST GET /api/v3/depth failed: {exc}") from exc
    try:
        payload = json.loads(body)
    except json.JSONDecodeError as exc:
        raise CollectorError(f"REST depth returned invalid JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise CollectorError("REST depth payload is not an object")
    last_update_id = payload.get("lastUpdateId")
    if isinstance(last_update_id, bool) or not isinstance(last_update_id, int) or last_update_id < 0:
        raise CollectorError("REST depth lastUpdateId is missing or invalid")
    payload["bids"] = _snapshot_levels(payload.get("bids"), "bids")
    payload["asks"] = _snapshot_levels(payload.get("asks"), "asks")
    return payload, recv_ns


def write_capture(path: Path, header: dict, records: list[dict], resyncs: int) -> None:
    lines = [dumps(header)] + [dumps(record) for record in records]
    footer = {
        "type": "footer",
        "version": SCHEMA_VERSION,
        "status": "complete",
        "records": len(records),
        "resyncs": resyncs,
        "content_sha256": file_sha256(lines),
    }
    payload = "".join(line + "\n" for line in lines) + dumps(footer) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(payload, encoding="utf-8")


async def capture_from_socket(
    ws,
    fetch_snapshot_fn: Callable[[], Awaitable[tuple[dict, int]]],
    *,
    symbol: str,
    duration_s: float,
    max_events: Optional[int],
    max_queue: int = MAX_QUEUE,
    max_buffer: int = MAX_BUFFER,
    max_resyncs: int = MAX_RESYNCS,
    clock: Callable[[], int] = time.perf_counter_ns,
    monotonic: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    log: Callable[[str], None] = _log,
) -> SyncSession:
    """Read ``ws`` until ``duration_s`` elapses and the book is synchronized."""
    if duration_s <= 0:
        raise CollectorError("duration must be positive")
    session = SyncSession(max_buffer=max_buffer, clock=clock)
    queue: asyncio.Queue = asyncio.Queue(maxsize=max_queue)
    reader_error: list[BaseException] = []
    stop = False
    seen = 0
    deadline = monotonic() + duration_s

    async def reader() -> None:
        try:
            while not stop:
                message = await ws.recv()
                recv_ns = clock()
                if isinstance(message, bytes):
                    message = message.decode("utf-8")
                try:
                    queue.put_nowait((recv_ns, message))
                except asyncio.QueueFull:
                    raise BufferOverflowError(
                        f"event queue exceeded {max_queue}; capture invalidated"
                    )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            reader_error.append(exc)

    def raise_reader_error() -> None:
        if not reader_error:
            return
        err = reader_error[0]
        if isinstance(err, (CollectorError, BufferOverflowError)):
            raise err
        raise CollectorError(f"websocket read failed: {err}") from err

    async def next_item():
        while True:
            raise_reader_error()
            if reader_task.done() and queue.empty():
                raise_reader_error()
                raise CollectorError("websocket closed before the capture finished")
            remaining = deadline - monotonic()
            if remaining <= 0:
                return None
            try:
                return await asyncio.wait_for(queue.get(), timeout=min(0.05, remaining))
            except asyncio.TimeoutError:
                continue

    def consume(item: tuple[int, str]) -> str:
        nonlocal seen
        if max_events is not None and seen >= max_events:
            return "stop"
        recv_ns, text = item
        event = parse_ws_payload(text, recv_ns, symbol)
        seen += 1
        session.push(event)
        if session.resyncs > max_resyncs:
            raise CollectorError(
                f"exceeded {max_resyncs} resynchronization attempts; capture invalidated"
            )
        if max_events is not None and seen >= max_events:
            return "stop"
        return "ok"

    async def drain() -> Optional[str]:
        while True:
            try:
                queued = queue.get_nowait()
            except asyncio.QueueEmpty:
                return None
            action = consume(queued)
            if action == "stop":
                return "stop"
        return None

    async def bridge_buffer() -> None:
        retries = 0
        while session.mode == "buffering":
            if session.first_u is None:
                item = await next_item()
                if item is None:
                    raise CollectorError("duration elapsed before any depth event")
                if consume(item) == "stop":
                    raise CollectorError("max_events reached before synchronization")
                continue
            snapshot, snap_ns = await fetch_snapshot_fn()
            stopped = await drain()
            raise_reader_error()
            status = session.accept_snapshot(
                snapshot["lastUpdateId"],
                snapshot["bids"],
                snapshot["asks"],
                snap_ns,
                clock(),
            )
            if session.resyncs > max_resyncs:
                raise CollectorError(
                    f"exceeded {max_resyncs} resynchronization attempts; capture invalidated"
                )
            if stopped == "stop" and not (status == "ok" and session.mode == "live"):
                raise CollectorError("max_events reached before synchronization")
            if status == "ok" and session.mode == "live":
                log(
                    f"synchronized {symbol} at lastUpdateId={session.book.last_update_id}"
                )
                return
            if status == "ok":
                log("bridged snapshot then lost continuity; resynchronizing")
                continue
            if status == "retry_snapshot":
                retries += 1
                log(
                    "snapshot lastUpdateId is older than the first buffered U; "
                    f"retry {retries}/{MAX_SNAPSHOT_RETRIES}"
                )
                if retries > MAX_SNAPSHOT_RETRIES:
                    raise CollectorError(
                        "REST snapshot remained older than the first buffered depth event"
                    )
                await sleep(min(1.0, 0.05 * (2**retries)))
                continue
            if status == "wait":
                log("snapshot is ahead of the buffer; waiting for a bridging depth event")
                item = await next_item()
                if item is None:
                    raise CollectorError("duration elapsed before the snapshot could be bridged")
                if consume(item) == "stop":
                    raise CollectorError("max_events reached before synchronization")
                continue
            if status == "gap":
                log("buffered depth does not bridge the snapshot; restarting synchronization")
                continue
            raise CollectorError(f"unknown bridge status: {status}")

    reader_task = asyncio.create_task(reader())
    try:
        while True:
            if session.mode == "buffering":
                await bridge_buffer()
            if max_events is not None and seen >= max_events:
                break
            item = await next_item()
            if item is None:
                break
            action = consume(item)
            if action == "stop":
                break
            if session.mode != "live":
                log("sequence gap; local book invalidated and resynchronization started")
                continue
        if session.mode != "live" or not session.book.synchronized:
            raise CollectorError("capture ended with an unsynchronized book")
        return session
    finally:
        stop = True
        reader_task.cancel()
        try:
            await reader_task
        except (asyncio.CancelledError, Exception):
            pass


async def collect(
    symbol: str,
    duration_s: float,
    output: Path,
    include_trades: bool = False,
    max_events: Optional[int] = None,
    snapshot_limit: int = 5000,
    depth_ms: int = 1000,
    timeout: float = 10.0,
) -> Path:
    symbol = symbol.upper()
    depth_stream = validate_request(symbol, duration_s, max_events, snapshot_limit, depth_ms)
    output = Path(output)
    partial = Path(str(output) + ".partial")
    if partial.exists():
        partial.unlink()
    header = {
        "type": "header",
        "version": SCHEMA_VERSION,
        "symbol": symbol,
        "market": "spot",
        "depth_stream": depth_stream,
        "include_trades": include_trades,
        "snapshot_limit": snapshot_limit,
        "clock": "perf_counter_ns",
    }
    url = stream_url(symbol, depth_stream, include_trades)
    try:
        async with aiohttp.ClientSession() as http:

            async def fetch() -> tuple[dict, int]:
                return await fetch_snapshot(http, symbol, snapshot_limit, timeout)

            try:
                connection = websockets.connect(
                    url,
                    open_timeout=timeout,
                    ping_interval=20,
                    ping_timeout=20,
                    max_queue=32,
                    close_timeout=2,
                )
            except TypeError:
                connection = websockets.connect(url, open_timeout=timeout, ping_interval=20, ping_timeout=20)
            async with connection as ws:
                session = await capture_from_socket(
                    ws,
                    fetch,
                    symbol=symbol,
                    duration_s=duration_s,
                    max_events=max_events,
                )
        write_capture(partial, header, session.out, session.resyncs)
        output.parent.mkdir(parents=True, exist_ok=True)
        os.replace(partial, output)
    except BaseException:
        if partial.exists():
            partial.unlink()
        raise
    _log(f"wrote {output} records={len(session.out)} resyncs={session.resyncs}")
    return output


async def check_connectivity(symbol: str, timeout: float) -> dict:
    symbol = symbol.upper()
    validate_request(symbol, 1.0, None, 5, 1000)
    if timeout <= 0:
        raise CollectorError("timeout must be positive")
    async with aiohttp.ClientSession() as http:
        snapshot, _recv = await fetch_snapshot(http, symbol, 5, timeout)
    url = stream_url(symbol, f"{symbol.lower()}@depth", False)
    try:
        async with websockets.connect(url, open_timeout=timeout, close_timeout=2) as ws:
            message = await asyncio.wait_for(ws.recv(), timeout=timeout)
    except asyncio.TimeoutError as exc:
        raise CollectorError(f"websocket timed out after {timeout}s waiting for a depth event") from exc
    except Exception as exc:
        if isinstance(exc, CollectorError):
            raise
        raise CollectorError(f"websocket connection failed: {exc}") from exc
    event = parse_ws_payload(message, time.perf_counter_ns(), symbol)
    if not isinstance(event, DepthMsg):
        raise CollectorError("websocket did not deliver a depthUpdate event")
    return {
        "ok": True,
        "symbol": symbol,
        "rest_last_update_id": snapshot["lastUpdateId"],
        "ws_event": "depthUpdate",
        "ws_U": event.U,
        "ws_u": event.u,
    }
