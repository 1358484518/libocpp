#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Charge-point WebSocket client used by 1.6 and 2.0.1 simulators."""
from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path
from typing import Any, Callable, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))

from rpc import CALL, CALLERROR, CALLRESULT, dumps, loads, make_call, make_error, make_result

log = logging.getLogger("ocpp_cp")


class ChargePointClient:
    def __init__(self, uri: str, subprotocol: str) -> None:
        self.uri = uri
        self.subprotocol = subprotocol
        self.ws: Any = None
        self._pending: dict[str, asyncio.Future] = {}
        self._reader_task: Optional[asyncio.Task] = None
        self.csms_calls: list[tuple[str, dict[str, Any]]] = []
        self.on_csms_call: Optional[Callable[[str, str, dict[str, Any]], dict[str, Any]]] = None
        self.connected = asyncio.Event()

    async def connect(self) -> None:
        import websockets

        self.ws = await websockets.connect(
            self.uri,
            subprotocols=[self.subprotocol],
            ping_interval=20,
            ping_timeout=20,
            max_size=2**20,
        )
        self._reader_task = asyncio.create_task(self._read_loop())
        self.connected.set()
        log.info("connected %s (%s)", self.uri, self.subprotocol)

    async def close(self) -> None:
        if self._reader_task:
            self._reader_task.cancel()
            try:
                await self._reader_task
            except asyncio.CancelledError:
                pass
        if self.ws is not None:
            await self.ws.close()
            self.ws = None

    async def _read_loop(self) -> None:
        assert self.ws is not None
        try:
            async for raw in self.ws:
                msg = loads(str(raw))
                msg_type = int(msg[0])
                unique_id = str(msg[1])
                if msg_type == CALLRESULT or msg_type == CALLERROR:
                    fut = self._pending.pop(unique_id, None)
                    if fut and not fut.done():
                        fut.set_result(msg)
                elif msg_type == CALL:
                    action = str(msg[2])
                    payload = msg[3] if len(msg) > 3 and isinstance(msg[3], dict) else {}
                    self.csms_calls.append((action, payload))
                    handler = self.on_csms_call
                    try:
                        body = handler(unique_id, action, payload) if handler else {"status": "Accepted"}
                        if body is None:
                            body = {}
                        await self.ws.send(dumps(make_result(unique_id, body)))
                    except Exception as exc:
                        await self.ws.send(dumps(make_error(unique_id, "InternalError", str(exc))))
        except Exception as exc:
            log.info("read loop ended: %s", exc)

    async def call(self, action: str, payload: dict[str, Any], timeout: float = 15.0) -> dict[str, Any]:
        if self.ws is None:
            raise RuntimeError("not connected")
        frame = make_call(action, payload)
        uid = str(frame[1])
        fut: asyncio.Future = asyncio.get_event_loop().create_future()
        self._pending[uid] = fut
        await self.ws.send(dumps(frame))
        reply = await asyncio.wait_for(fut, timeout=timeout)
        if int(reply[0]) == CALLERROR:
            raise RuntimeError(f"CALLERROR {reply}")
        payload_out = reply[2] if len(reply) > 2 else {}
        return payload_out if isinstance(payload_out, dict) else {}
