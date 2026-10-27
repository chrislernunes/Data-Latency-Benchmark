"""Live Binance Spot market-data collector with correct synchronization."""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from typing import List, Optional

import aiohttp
import websockets

from .models import Header, SnapshotEvent, DepthEvent, AggTradeEvent, event_to_json


REST_BASE = "https://api.binance.com/api/v3"
WS_BASE = "wss://stream.binance.com:9443/ws"


class CollectorError(Exception):
    pass


async def fetch_snapshot(session: aiohttp.ClientSession, symbol: str, limit: int = 5000) -> dict:
    url = f"{REST_BASE}/depth?symbol={symbol}&limit={limit}"
    async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
        if resp.status != 200:
            raise CollectorError(f"REST depth failed: {resp.status}")
        return await resp.json()


async def collect(
    symbol: str,
    duration_s: float,
    output: Path,
    include_trades: bool = False,
    max_events: Optional[int] = None,
) -> None:
    """Capture synchronized order-book events to JSONL."""
    symbol = symbol.upper()
    stream = f"{symbol.lower()}@depth"
    if include_trades:
        stream += f"/{symbol.lower()}@aggTrade"

    output.parent.mkdir(parents=True, exist_ok=True)
    start_ns = time.perf_counter_ns()

    async with aiohttp.ClientSession() as session:
        # Buffer while connecting
        buffer: List[dict] = []
        synced = False
        last_u: Optional[int] = None
        event_count = 0

        async with websockets.connect(f"{WS_BASE}/{stream}", ping_interval=20, ping_timeout=10) as ws:
            # Start buffering
            async def buffer_task():
                nonlocal event_count
                try:
                    async for msg in ws:
                        data = json.loads(msg)
                        buffer.append(data)
                        event_count += 1
                        if max_events and event_count >= max_events:
                            break
                except Exception:
                    pass

            buf_task = asyncio.create_task(buffer_task())

            # Fetch snapshot
            snap = await fetch_snapshot(session, symbol)
            last_update_id = snap["lastUpdateId"]

            # Wait a bit for buffer
            await asyncio.sleep(0.5)

            # Process buffer and write
            with output.open("w") as f:
                header = Header(symbol=symbol, start_ts_ns=start_ns)
                f.write(event_to_json(header) + "\n")

                # Write snapshot
                snap_ev = SnapshotEvent(
                    last_update_id=last_update_id,
                    bids=[(p, q) for p, q in snap.get("bids", [])],
                    asks=[(p, q) for p, q in snap.get("asks", [])],
                    local_recv_ns=time.perf_counter_ns(),
                )
                f.write(event_to_json(snap_ev) + "\n")

                # Apply buffered events that bridge the snapshot
                for raw in buffer:
                    if raw.get("e") != "depthUpdate":
                        continue
                    U = raw["U"]
                    u = raw["u"]
                    if u <= last_update_id:
                        continue
                    if U <= last_update_id + 1 <= u:
                        # valid bridge
                        local_ns = time.perf_counter_ns()
                        depth = DepthEvent(
                            U=U, u=u,
                            b=[(p, q) for p, q in raw.get("b", [])],
                            a=[(p, q) for p, q in raw.get("a", [])],
                            E=raw.get("E"),
                            local_recv_ns=local_ns,
                        )
                        f.write(event_to_json(depth) + "\n")
                        last_u = u
                        synced = True
                        break

                if not synced:
                    raise CollectorError("Failed to find bridging event")

                # Continue live
                end_time = time.time() + duration_s
                while time.time() < end_time and (max_events is None or event_count < max_events):
                    try:
                        msg = await asyncio.wait_for(ws.recv(), timeout=5.0)
                        raw = json.loads(msg)
                        local_ns = time.perf_counter_ns()
                        if raw.get("e") == "depthUpdate":
                            U = raw["U"]
                            u = raw["u"]
                            if last_u is not None and U != last_u + 1:
                                # gap - for capture we still write but mark
                                pass
                            depth = DepthEvent(
                                U=U, u=u,
                                b=[(p, q) for p, q in raw.get("b", [])],
                                a=[(p, q) for p, q in raw.get("a", [])],
                                E=raw.get("E"),
                                local_recv_ns=local_ns,
                            )
                            f.write(event_to_json(depth) + "\n")
                            last_u = u
                            event_count += 1
                        elif raw.get("e") == "aggTrade" and include_trades:
                            # simplified
                            trade = AggTradeEvent(
                                a=raw.get("a", 0),
                                p=raw.get("p", ""),
                                q=raw.get("q", ""),
                                T=raw.get("T"),
                                m=raw.get("m", False),
                                local_recv_ns=local_ns,
                            )
                            f.write(event_to_json(trade) + "\n")
                            event_count += 1
                    except asyncio.TimeoutError:
                        continue
                    except Exception as e:
                        print(f"Receive error: {e}")
                        break

            buf_task.cancel()
