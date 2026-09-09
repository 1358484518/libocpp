#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""OCPP 2.0.1 simulated charge point.

Mirrors the 1.6 flow in charge_point_v16.py / src/charge_point.cpp, using
TransactionEvent Started/Updated/Ended instead of StartTransaction/StopTransaction.
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import sys
import uuid
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from cp_client import ChargePointClient
from rpc import utc_now

log = logging.getLogger("cp201")


class ChargePoint201:
    def __init__(self, uri: str) -> None:
        self.client = ChargePointClient(uri, "ocpp2.0.1")
        self.transaction_id: str | None = None
        self.seq_no = 0
        self.remote_start_event = asyncio.Event()
        self.remote_stop_event = asyncio.Event()
        self.reset_event = asyncio.Event()
        self.pending_remote_id_tag: str | None = None
        self.client.on_csms_call = self._on_csms

    def _on_csms(self, _uid: str, action: str, payload: dict[str, Any]) -> dict[str, Any]:
        log.info("CSMS CALL %s %s", action, payload)
        if action == "RequestStartTransaction":
            token = (payload.get("idToken") or {}).get("idToken", "DEADBEEF")
            self.pending_remote_id_tag = str(token)
            self.remote_start_event.set()
            return {"status": "Accepted"}
        if action == "RequestStopTransaction":
            self.remote_stop_event.set()
            return {"status": "Accepted"}
        if action == "Reset":
            self.reset_event.set()
            return {"status": "Accepted"}
        if action == "UnlockConnector":
            return {"status": "Unlocked"}
        if action == "ChangeAvailability":
            return {"status": "Accepted"}
        if action == "GetVariables":
            items = []
            for item in payload.get("getVariableData") or []:
                items.append(
                    {
                        "attributeStatus": "Accepted",
                        "component": item.get("component"),
                        "variable": item.get("variable"),
                        "attributeValue": "60",
                    }
                )
            return {"getVariableResult": items}
        if action == "SetVariables":
            items = []
            for item in payload.get("setVariableData") or []:
                items.append(
                    {
                        "attributeStatus": "Accepted",
                        "component": item.get("component"),
                        "variable": item.get("variable"),
                    }
                )
            return {"setVariableResult": items}
        if action == "TriggerMessage":
            return {"status": "Accepted"}
        if action == "GetBaseReport":
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
                "reason": "PowerUp",
                "chargingStation": {
                    "model": "Yeti",
                    "vendorName": "Pionix",
                    "firmwareVersion": "0.1-sim",
                    "serialNumber": "cp-sim-201",
                },
            },
        )

    async def status(self, connector_status: str = "Available", evse_id: int = 1, connector_id: int = 1) -> dict[str, Any]:
        return await self.client.call(
            "StatusNotification",
            {
                "timestamp": utc_now(),
                "connectorStatus": connector_status,
                "evseId": evse_id,
                "connectorId": connector_id,
            },
        )

    async def authorize(self, id_tag: str = "DEADBEEF") -> dict[str, Any]:
        return await self.client.call(
            "Authorize",
            {"idToken": {"idToken": id_tag, "type": "ISO14443"}},
        )

    async def _tx_event(self, event_type: str, extra: dict[str, Any]) -> dict[str, Any]:
        if self.transaction_id is None:
            self.transaction_id = str(uuid.uuid4())
        body: dict[str, Any] = {
            "eventType": event_type,
            "timestamp": utc_now(),
            "triggerReason": extra.pop("triggerReason", "Authorized"),
            "seqNo": self.seq_no,
            "transactionInfo": {"transactionId": self.transaction_id, **extra.pop("tx_extra", {})},
            "evse": {"id": extra.pop("evse_id", 1), "connectorId": extra.pop("connector_id", 1)},
        }
        body.update(extra)
        self.seq_no += 1
        return await self.client.call("TransactionEvent", body)

    async def start_transaction(self, id_tag: str = "DEADBEEF") -> dict[str, Any]:
        self.seq_no = 0
        self.transaction_id = str(uuid.uuid4())
        resp = await self._tx_event(
            "Started",
            {
                "triggerReason": "Authorized",
                "idToken": {"idToken": id_tag, "type": "ISO14443"},
                "meterValue": [
                    {
                        "timestamp": utc_now(),
                        "sampledValue": [
                            {
                                "value": 0,
                                "measurand": "Energy.Active.Import.Register",
                                "location": "Outlet",
                                "unitOfMeasure": {"unit": "Wh"},
                            }
                        ],
                    }
                ],
            },
        )
        await self.status("Occupied")
        return resp

    async def meter_update(self, wh: int = 1200) -> dict[str, Any]:
        return await self._tx_event(
            "Updated",
            {
                "triggerReason": "MeterValuePeriodic",
                "meterValue": [
                    {
                        "timestamp": utc_now(),
                        "sampledValue": [
                            {
                                "value": wh,
                                "measurand": "Energy.Active.Import.Register",
                                "unitOfMeasure": {"unit": "Wh"},
                            }
                        ],
                    }
                ],
            },
        )

    async def stop_transaction(self, reason: str = "Local", wh: int = 2500) -> dict[str, Any]:
        resp = await self._tx_event(
            "Ended",
            {
                "triggerReason": "StopAuthorized" if reason != "Remote" else "RemoteStop",
                "tx_extra": {"stoppedReason": reason},
                "meterValue": [
                    {
                        "timestamp": utc_now(),
                        "sampledValue": [
                            {
                                "value": wh,
                                "context": "Transaction.End",
                                "measurand": "Energy.Active.Import.Register",
                                "unitOfMeasure": {"unit": "Wh"},
                            }
                        ],
                    }
                ],
            },
        )
        self.transaction_id = None
        await self.status("Available")
        return resp

    async def heartbeat(self) -> dict[str, Any]:
        return await self.client.call("Heartbeat", {})

    async def run_local_session(self) -> None:
        boot = await self.boot()
        if boot.get("status") != "Accepted":
            raise RuntimeError(boot)
        await self.status("Available")
        auth = await self.authorize("DEADBEEF")
        if auth.get("idTokenInfo", {}).get("status") != "Accepted":
            raise RuntimeError(auth)
        started = await self.start_transaction("DEADBEEF")
        log.info("Started conf %s", started)
        await self.meter_update(1500)
        await self.stop_transaction("Local")
        await self.heartbeat()


async def amain(url: str, wait_remote_stop: bool) -> None:
    cp = ChargePoint201(url)
    await cp.connect()
    await cp.run_local_session()
    print("2.0.1 local session completed")
    if wait_remote_stop:
        print("waiting for RequestStartTransaction / RequestStopTransaction...")
        await cp.status("Available")
        await cp.remote_start_event.wait()
        await cp.start_transaction(cp.pending_remote_id_tag or "DEADBEEF")
        await cp.remote_stop_event.wait()
        await cp.stop_transaction("Remote")
        print("2.0.1 remote stop completed")
    await cp.close()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    p = argparse.ArgumentParser()
    p.add_argument("--url", default="ws://127.0.0.1:9000/cp201")
    p.add_argument("--wait-remote-stop", action="store_true")
    args = p.parse_args()
    asyncio.run(amain(args.url, args.wait_remote_stop))


if __name__ == "__main__":
    main()
