#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Integration tests: mock CSMS + simulated 1.6 / 2.0.1 charge points.

1.6 flow matches src/charge_point.cpp (auth DEADBEEF, start/stop transaction).
2.0.1 uses the same hardware story with TransactionEvent + RequestStopTransaction.
"""
from __future__ import annotations

import asyncio
import logging
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from charge_point_v16 import ChargePoint16
from charge_point_v201 import ChargePoint201
from server import SUBPROTOCOL_16, SUBPROTOCOL_201, serve

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


class OcppCsmsIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.ws_server, self.csms, self.base_uri = await serve("127.0.0.1", 0)
        self.addAsyncCleanup(self._shutdown)

    async def _shutdown(self) -> None:
        self.ws_server.close()
        await self.ws_server.wait_closed()

    def _url(self, cp_id: str) -> str:
        return f"{self.base_uri}/{cp_id}"

    async def test_v16_local_start_stop(self) -> None:
        cp = ChargePoint16(self._url("cp16-local"))
        await cp.connect()
        try:
            await cp.run_local_session()
            st = self.csms.get("cp16-local")
            self.assertIsNotNone(st)
            assert st is not None
            self.assertEqual(st.protocol, SUBPROTOCOL_16)
            actions = [a for direction, a, _payload in st.log if direction == "cp->csms"]
            self.assertIn("BootNotification", actions)
            self.assertIn("StartTransaction", actions)
            self.assertIn("StopTransaction", actions)
            self.assertEqual(st.active_tx, {})
        finally:
            await cp.close()

    async def test_v16_remote_stop(self) -> None:
        cp = ChargePoint16(self._url("cp16-remote"))
        await cp.connect()
        try:
            boot = await cp.boot()
            self.assertEqual(boot["status"], "Accepted")
            await cp.status(1, "Available")
            await cp.start_transaction("DEADBEEF")
            self.assertIsNotNone(cp.transaction_id)
            result = await self.csms.remote_stop("cp16-remote")
            self.assertEqual(int(result[0]), 3)
            conf = result[2]
            self.assertEqual(conf.get("status"), "Accepted")
            await asyncio.wait_for(cp.remote_stop_event.wait(), timeout=5)
            await cp.stop_transaction(reason="Remote")
            self.assertIsNone(cp.transaction_id)
        finally:
            await cp.close()

    async def test_v201_local_start_stop(self) -> None:
        cp = ChargePoint201(self._url("cp201-local"))
        await cp.connect()
        try:
            await cp.run_local_session()
            st = self.csms.get("cp201-local")
            self.assertIsNotNone(st)
            assert st is not None
            self.assertEqual(st.protocol, SUBPROTOCOL_201)
            actions = [a for d, a, _ in st.log if d == "cp->csms"]
            self.assertIn("BootNotification", actions)
            self.assertIn("Authorize", actions)
            self.assertIn("TransactionEvent", actions)
            self.assertEqual(st.active_tx, {})
        finally:
            await cp.close()

    async def test_v201_remote_start_and_stop(self) -> None:
        cp = ChargePoint201(self._url("cp201-remote"))
        await cp.connect()
        try:
            boot = await cp.boot()
            self.assertEqual(boot["status"], "Accepted")
            await cp.status("Available")
            start_conf = await self.csms.remote_start("cp201-remote", "DEADBEEF", 1)
            self.assertEqual(int(start_conf[0]), 3)
            self.assertEqual(start_conf[2].get("status"), "Accepted")
            await asyncio.wait_for(cp.remote_start_event.wait(), timeout=5)
            await cp.start_transaction(cp.pending_remote_id_tag or "DEADBEEF")
            self.assertIsNotNone(cp.transaction_id)
            stop_conf = await self.csms.remote_stop("cp201-remote")
            self.assertEqual(int(stop_conf[0]), 3)
            self.assertEqual(stop_conf[2].get("status"), "Accepted")
            await asyncio.wait_for(cp.remote_stop_event.wait(), timeout=5)
            await cp.stop_transaction("Remote")
            self.assertIsNone(cp.transaction_id)
            st = self.csms.get("cp201-remote")
            assert st is not None
            self.assertEqual(st.active_tx, {})
        finally:
            await cp.close()

    async def test_v201_get_variables(self) -> None:
        cp = ChargePoint201(self._url("cp201-vars"))
        await cp.connect()
        try:
            await cp.boot()
            reply = await self.csms.send_call(
                "cp201-vars",
                "GetVariables",
                {
                    "getVariableData": [
                        {"component": {"name": "OCPPCommCtrlr"}, "variable": {"name": "HeartbeatInterval"}}
                    ]
                },
            )
            self.assertEqual(int(reply[0]), 3)
            results = reply[2].get("getVariableResult") or []
            self.assertTrue(results)
            self.assertEqual(results[0].get("attributeStatus"), "Accepted")
        finally:
            await cp.close()


if __name__ == "__main__":
    unittest.main()
