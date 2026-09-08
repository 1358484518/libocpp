#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""OCPP 1.6J simulated charge point (mirrors src/charge_point.cpp CLI flow)."""
from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from cp_client import ChargePointClient
from rpc import utc_now

log = logging.getLogger("cp16")


class ChargePoint16:
    """Boot → Status → Authorize → StartTransaction → MeterValues → StopTransaction."""

    def __init__(self, uri: str) -> None:
        self.client = ChargePointClient(uri, "ocpp1.6")
        self.transaction_id: int | None = None
        self.remote_start_event = asyncio.Event()
        self.remote_stop_event = asyncio.Event()
        self.reset_event = asyncio.Event()
        self.client.on_csms_call = self._on_csms

    def _on_csms(self, _uid: str, action: str, payload: dict[str, Any]) -> dict[str, Any]:
        log.info("CSMS CALL %s %s", action, payload)
        if action == "RemoteStartTransaction":
            self.remote_start_event.set()
            return {"status": "Accepted"}
        if action == "RemoteStopTransaction":
            self.remote_stop_event.set()
            return {"status": "Accepted"}
        if action == "Reset":
            self.reset_event.set()
            return {"status": "Accepted"}
        if action == "UnlockConnector":
            return {"status": "Unlocked"}
        if action == "ChangeAvailability":
            return {"status": "Accepted"}
        if action == "GetConfiguration":
            return {
                "configurationKey": [
                    {"key": "HeartbeatInterval", "readonly": False, "value": "60"},
                    {"key": "NumberOfConnectors", "readonly": True, "value": "1"},
                ]
            }
        if action == "ChangeConfiguration":
            return {"status": "Accepted"}
        if action == "TriggerMessage":
            return {"status": "Accepted"}
        if action == "ClearCache":
            return {"status": "Accepted"}
        return {"status": "Accepted"}

    async def connect(self) -> None:
        await self.client.connect()

    async def close(self) -> None:
        await self.client.close()

    async def boot(self) -> dict[str, Any]:
        return await self.client.call(
            "BootNotification",
            {
                "chargePointVendor": "Pionix",
                "chargePointModel": "Yeti",
                "chargePointSerialNumber": "cp-sim-16",
                "firmwareVersion": "0.1-sim",
            },
        )

    async def status(self, connector_id: int = 1, status: str = "Available") -> dict[str, Any]:
        return await self.client.call(
            "StatusNotification",
            {
                "connectorId": connector_id,
                "errorCode": "NoError",
                "status": status,
            },
        )

    async def authorize(self, id_tag: str = "DEADBEEF") -> dict[str, Any]:
        return await self.client.call("Authorize", {"idTag": id_tag})

    async def start_transaction(self, id_tag: str = "DEADBEEF", connector_id: int = 1, meter_start: int = 0) -> dict[str, Any]:
        resp = await self.client.call(
            "StartTransaction",
            {
                "connectorId": connector_id,
                "idTag": id_tag,
                "meterStart": meter_start,
                "timestamp": utc_now(),
            },
        )
        self.transaction_id = int(resp["transactionId"])
        await self.status(connector_id, "Charging")
        return resp

    async def meter_values(self, connector_id: int = 1, wh: int = 1000) -> dict[str, Any]:
        if self.transaction_id is None:
            raise RuntimeError("no transaction")
        return await self.client.call(
            "MeterValues",
            {
                "connectorId": connector_id,
                "transactionId": self.transaction_id,
                "meterValue": [
                    {
                        "timestamp": utc_now(),
                        "sampledValue": [{"value": str(wh), "measurand": "Energy.Active.Import.Register", "unit": "Wh"}],
                    }
                ],
            },
        )

    async def stop_transaction(self, meter_stop: int = 2500, reason: str = "Local") -> dict[str, Any]:
        if self.transaction_id is None:
            raise RuntimeError("no transaction")
        resp = await self.client.call(
            "StopTransaction",
            {
                "transactionId": self.transaction_id,
                "timestamp": utc_now(),
                "meterStop": meter_stop,
                "reason": reason,
            },
        )
        self.transaction_id = None
        await self.status(1, "Available")
        return resp

    async def heartbeat(self) -> dict[str, Any]:
        return await self.client.call("Heartbeat", {})

    async def run_local_session(self) -> None:
        """Same sequence as src/charge_point.cpp start_transaction / stop_transaction."""
        boot = await self.boot()
        if boot.get("status") != "Accepted":
            raise RuntimeError(boot)
        await self.status(0, "Available")
        await self.status(1, "Preparing")
        auth = await self.authorize("DEADBEEF")
        if auth.get("idTagInfo", {}).get("status") != "Accepted":
            raise RuntimeError(auth)
        await self.start_transaction("DEADBEEF")
        await self.meter_values(wh=1200)
        await self.stop_transaction()
        await self.heartbeat()


async def amain(url: str, wait_remote_stop: bool) -> None:
    cp = ChargePoint16(url)
    await cp.connect()
    await cp.run_local_session()
    print("1.6 local session completed")
    if wait_remote_stop:
        print("waiting for RemoteStart then RemoteStop from CSMS...")
        await cp.status(1, "Available")
        await cp.remote_start_event.wait()
        await cp.start_transaction("DEADBEEF")
        await cp.remote_stop_event.wait()
        await cp.stop_transaction(reason="Remote")
        print("1.6 remote stop completed")
    await cp.close()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    p = argparse.ArgumentParser()
    p.add_argument("--url", default="ws://127.0.0.1:9000/cp001")
    p.add_argument("--wait-remote-stop", action="store_true")
    args = p.parse_args()
    asyncio.run(amain(args.url, args.wait_remote_stop))


if __name__ == "__main__":
    main()
