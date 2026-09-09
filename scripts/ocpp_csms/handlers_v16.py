#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""OCPP 1.6 JSON CSMS handlers (Core + common extras)."""
from __future__ import annotations

from typing import Any

from rpc import utc_now
from state import ChargePointState


def handle_v16(state: ChargePointState, action: str, payload: dict[str, Any]) -> dict[str, Any]:
    payload = payload or {}
    state.record("cp->csms", action, payload)

    if action == "BootNotification":
        state.boot_payload = payload
        return {"status": "Accepted", "currentTime": utc_now(), "interval": 60}

    if action == "Heartbeat":
        state.last_heartbeat = utc_now()
        return {"currentTime": utc_now()}

    if action == "StatusNotification":
        cid = int(payload.get("connectorId", 0))
        state.connectors[cid] = str(payload.get("status", "Unknown"))
        return {}

    if action == "Authorize":
        tag = str(payload.get("idTag", ""))
        status = state.id_tags.get(tag, "Accepted")
        return {"idTagInfo": {"status": status}}

    if action == "StartTransaction":
        tx_id = state.next_tx_numeric
        state.next_tx_numeric += 1
        tag = str(payload.get("idTag", ""))
        state.active_tx = {
            "protocol": "ocpp1.6",
            "transactionId": tx_id,
            "idTag": tag,
            "connectorId": payload.get("connectorId", 1),
            "meterStart": payload.get("meterStart", 0),
        }
        return {"transactionId": tx_id, "idTagInfo": {"status": state.id_tags.get(tag, "Accepted")}}

    if action == "StopTransaction":
        state.active_tx = {}
        tag = str(payload.get("idTag", "") or "")
        info: dict[str, Any] = {"status": "Accepted"}
        if tag:
            info["status"] = state.id_tags.get(tag, "Accepted")
        return {"idTagInfo": info}

    if action == "MeterValues":
        return {}

    if action == "DataTransfer":
        return {"status": "Accepted", "data": payload.get("data")}

    if action == "DiagnosticsStatusNotification":
        return {}
    if action == "FirmwareStatusNotification":
        return {}
    if action == "SecurityEventNotification":
        return {}
    if action == "SignCertificate":
        return {"status": "Accepted"}
    if action == "LogStatusNotification":
        return {}
    if action == "SignedFirmwareStatusNotification":
        return {}

    # Unknown but valid CALL: empty payload is often legal for 1.6
    return {}


def csms_call_v16(action: str, **kwargs: Any) -> dict[str, Any]:
    """Build CSMS -> Charge Point CALL payloads."""
    if action == "RemoteStartTransaction":
        body: dict[str, Any] = {"idTag": kwargs.get("id_tag", "DEADBEEF")}
        if kwargs.get("connector_id") is not None:
            body["connectorId"] = int(kwargs["connector_id"])
        return body
    if action == "RemoteStopTransaction":
        return {"transactionId": int(kwargs["transaction_id"])}
    if action == "Reset":
        return {"type": kwargs.get("reset_type", "Soft")}
    if action == "UnlockConnector":
        return {"connectorId": int(kwargs.get("connector_id", 1))}
    if action == "ChangeAvailability":
        return {
            "connectorId": int(kwargs.get("connector_id", 0)),
            "type": kwargs.get("avail_type", "Operative"),
        }
    if action == "GetConfiguration":
        keys = kwargs.get("keys") or []
        return {"key": keys} if keys else {}
    if action == "ChangeConfiguration":
        return {"key": kwargs["key"], "value": str(kwargs["value"])}
    if action == "TriggerMessage":
        body = {"requestedMessage": kwargs.get("requested", "StatusNotification")}
        if kwargs.get("connector_id") is not None:
            body["connectorId"] = int(kwargs["connector_id"])
        return body
    if action == "ClearCache":
        return {}
    if action == "GetLocalListVersion":
        return {}
    raise ValueError(f"unsupported CSMS action {action}")
