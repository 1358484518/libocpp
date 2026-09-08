#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Async OCPP 1.6J + 2.0.1 CSMS (WebSocket JSON)."""
from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path
from typing import Any, Optional
from urllib.parse import unquote

sys.path.insert(0, str(Path(__file__).resolve().parent))

from handlers_v16 import csms_call_v16, handle_v16
from handlers_v201 import csms_call_v201, handle_v201
from rpc import CALL, CALLERROR, CALLRESULT, dumps, loads, make_call, make_error, make_result
from state import ChargePointState

log = logging.getLogger("ocpp_csms")

SUBPROTOCOL_16 = "ocpp1.6"
SUBPROTOCOL_201 = "ocpp2.0.1"


def cp_id_from_path(path: str) -> str:
    parts = [unquote(p) for p in path.split("/") if p]
    return parts[-1] if parts else "unknown"


def websocket_path(ws: Any) -> str:
    if getattr(ws, "path", None):
        return str(ws.path)
    req = getattr(ws, "request", None)
    if req is not None and getattr(req, "path", None):
        return str(req.path)
    return "/"


def websocket_subprotocol(ws: Any) -> str:
    sp = getattr(ws, "subprotocol", None)
    if sp:
        return str(sp)
    return SUBPROTOCOL_16


class CsmsServer:
    def __init__(self) -> None:
        self.cps: dict[str, ChargePointState] = {}
        self._pending: dict[tuple[str, str], asyncio.Future] = {}

    def get(self, cp_id: str) -> Optional[ChargePointState]:
        return self.cps.get(cp_id)

    async def handle(self, websocket: Any, path: Optional[str] = None) -> None:
        if path is None:
            path = websocket_path(websocket)
        cp_id = cp_id_from_path(path)
        proto = websocket_subprotocol(websocket)
        if proto not in (SUBPROTOCOL_16, SUBPROTOCOL_201):
            # some clients omit subprotocol; infer from query or default 1.6
            proto = SUBPROTOCOL_16
        state = ChargePointState(cp_id=cp_id, protocol=proto, websocket=websocket)
        self.cps[cp_id] = state
        log.info("connected %s protocol=%s path=%s", cp_id, proto, path)
        try:
            async for raw in websocket:
                await self._on_message(state, str(raw))
        except Exception as exc:
            log.info("disconnected %s: %s", cp_id, exc)
        finally:
            if self.cps.get(cp_id) is state:
                state.websocket = None

    async def _on_message(self, state: ChargePointState, raw: str) -> None:
        try:
            msg = loads(raw)
        except Exception:
            log.warning("bad json from %s: %s", state.cp_id, raw[:200])
            return
        msg_type = int(msg[0])
        unique_id = str(msg[1])
        if msg_type == CALL:
            action = str(msg[2])
            payload = msg[3] if len(msg) > 3 else {}
            if not isinstance(payload, dict):
                payload = {}
            try:
                if state.protocol == SUBPROTOCOL_201:
                    result = handle_v201(state, action, payload)
                else:
                    result = handle_v16(state, action, payload)
                await state.websocket.send(dumps(make_result(unique_id, result)))
            except Exception as exc:
                log.exception("handler %s", action)
                await state.websocket.send(dumps(make_error(unique_id, "InternalError", str(exc))))
        elif msg_type in (CALLRESULT, CALLERROR):
            key = (state.cp_id, unique_id)
            fut = self._pending.pop(key, None)
            if fut and not fut.done():
                fut.set_result(msg)
        else:
            log.warning("unknown message type %s", msg_type)

    async def send_call(self, cp_id: str, action: str, payload: dict[str, Any], timeout: float = 10.0) -> list[Any]:
        state = self.cps.get(cp_id)
        if state is None or state.websocket is None:
            raise RuntimeError(f"charge point {cp_id} not connected")
        frame = make_call(action, payload)
        unique_id = str(frame[1])
        loop = asyncio.get_event_loop()
        fut: asyncio.Future = loop.create_future()
        self._pending[(cp_id, unique_id)] = fut
        state.record("csms->cp", action, payload)
        await state.websocket.send(dumps(frame))
        try:
            return await asyncio.wait_for(fut, timeout=timeout)
        except asyncio.TimeoutError:
            self._pending.pop((cp_id, unique_id), None)
            raise

    async def remote_start(self, cp_id: str, id_tag: str = "DEADBEEF", connector_or_evse: int = 1) -> list[Any]:
        state = self.cps[cp_id]
        if state.protocol == SUBPROTOCOL_201:
            return await self.send_call(
                cp_id, "RequestStartTransaction", csms_call_v201("RequestStartTransaction", id_tag=id_tag, evse_id=connector_or_evse)
            )
        return await self.send_call(
            cp_id, "RemoteStartTransaction", csms_call_v16("RemoteStartTransaction", id_tag=id_tag, connector_id=connector_or_evse)
        )

    async def remote_stop(self, cp_id: str, transaction_id: Any | None = None) -> list[Any]:
        state = self.cps[cp_id]
        tx = transaction_id
        if tx is None:
            tx = state.active_tx.get("transactionId")
        if tx is None:
            raise RuntimeError("no active transaction")
        if state.protocol == SUBPROTOCOL_201:
            return await self.send_call(cp_id, "RequestStopTransaction", csms_call_v201("RequestStopTransaction", transaction_id=tx))
        return await self.send_call(cp_id, "RemoteStopTransaction", csms_call_v16("RemoteStopTransaction", transaction_id=tx))

    async def reset(self, cp_id: str, reset_type: str | None = None) -> list[Any]:
        state = self.cps[cp_id]
        if state.protocol == SUBPROTOCOL_201:
            return await self.send_call(
                cp_id, "Reset", csms_call_v201("Reset", reset_type=reset_type or "Immediate")
            )
        return await self.send_call(cp_id, "Reset", csms_call_v16("Reset", reset_type=reset_type or "Soft"))


async def serve(host: str, port: int, server: Optional[CsmsServer] = None) -> tuple[Any, CsmsServer, str]:
    try:
        import websockets
    except ImportError as exc:
        raise SystemExit("install websockets: pip install -r scripts/ocpp_csms/requirements.txt") from exc

    csms = server or CsmsServer()

    async def _handler(websocket: Any, path: Optional[str] = None) -> None:
        await csms.handle(websocket, path)

    ws_server = await websockets.serve(
        _handler,
        host,
        port,
        subprotocols=[SUBPROTOCOL_16, SUBPROTOCOL_201],
        ping_interval=20,
        ping_timeout=20,
        max_size=2**20,
    )
    bound = ws_server.sockets[0].getsockname()
    actual_port = bound[1]
    uri = f"ws://{host}:{actual_port}"
    log.info("CSMS listening on %s (ocpp1.6 / ocpp2.0.1)", uri)
    return ws_server, csms, uri


async def _stdin_commands(csms: CsmsServer) -> None:
    loop = asyncio.get_event_loop()
    reader = asyncio.StreamReader()
    protocol = asyncio.StreamReaderProtocol(reader)
    await loop.connect_read_pipe(lambda: protocol, sys.stdin)
    print("commands: list | remote_start <cp> [idTag] | remote_stop <cp> | reset <cp> [Soft|Hard|Immediate]", flush=True)
    while True:
        line = await reader.readline()
        if not line:
            break
        parts = line.decode().strip().split()
        if not parts:
            continue
        try:
            cmd = parts[0]
            if cmd == "list":
                for cid, st in csms.cps.items():
                    print(f"  {cid} proto={st.protocol} tx={st.active_tx} ws={'up' if st.websocket else 'down'}")
            elif cmd == "remote_start":
                msg = await csms.remote_start(parts[1], parts[2] if len(parts) > 2 else "DEADBEEF")
                print("CALLRESULT", msg)
            elif cmd == "remote_stop":
                msg = await csms.remote_stop(parts[1])
                print("CALLRESULT", msg)
            elif cmd == "reset":
                msg = await csms.reset(parts[1], parts[2] if len(parts) > 2 else None)
                print("CALLRESULT", msg)
            else:
                print("unknown command")
        except Exception as exc:
            print("error:", exc)


async def amain(host: str, port: int, interactive: bool) -> None:
    ws_server, csms, uri = await serve(host, port)
    print(f"CSMS {uri}/<chargePointId>  subprotocols ocpp1.6 ocpp2.0.1", flush=True)
    if interactive and sys.stdin.isatty():
        await _stdin_commands(csms)
    else:
        await asyncio.Future()
    ws_server.close()
    await ws_server.wait_closed()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    p = argparse.ArgumentParser(description="Mock OCPP 1.6J / 2.0.1 CSMS")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=9000)
    p.add_argument("--no-stdin", action="store_true")
    args = p.parse_args()
    try:
        asyncio.run(amain(args.host, args.port, interactive=not args.no_stdin))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
