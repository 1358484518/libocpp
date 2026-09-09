#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""OCPP 2.0.1 CSMS handlers (core charging + provisioning/auth)."""
from __future__ import annotations

from typing import Any

from rpc import utc_now
from state import ChargePointState


def handle_v201(state: ChargePointState, action: str, payload: dict[str, Any]) -> dict[str, Any]:
    payload = payload or {}
    state.record("cp->csms", action, payload)

    if action == "BootNotification":
        state.boot_payload = payload
        return {"status": "Accepted", "currentTime": utc_now(), "interval": 60}

    if action == "Heartbeat":
        state.last_heartbeat = utc_now()
        return {"currentTime": utc_now()}

    if action == "StatusNotification":
        evse = int(payload.get("evseId", 1))
        conn = int(payload.get("connectorId", 1))
        state.connectors[evse * 100 + conn] = str(payload.get("connectorStatus", "Unknown"))
        return {}

    if action == "Authorize":
        token = (payload.get("idToken") or {}).get("idToken", "")
        status = state.id_tags.get(str(token), "Accepted")
        return {"idTokenInfo": {"status": status}}

    if action == "TransactionEvent":
        event = payload.get("eventType")
        info = payload.get("transactionInfo") or {}
        tx_id = str(info.get("transactionId", ""))
        if event == "Started":
            state.active_tx = {
                "protocol": "ocpp2.0.1",
                "transactionId": tx_id,
                "seqNo": payload.get("seqNo", 0),
                "evse": payload.get("evse"),
            }
            token = (payload.get("idToken") or {}).get("idToken")
            resp: dict[str, Any] = {}
            if token is not None:
                resp["idTokenInfo"] = {"status": state.id_tags.get(str(token), "Accepted")}
            return resp
        if event == "Ended":
            state.active_tx = {}
            return {}
        return {}

    if action == "MeterValues":
        return {}

    if action == "NotifyReport":
        return {}
    if action == "NotifyEvent":
        return {}
    if action == "SecurityEventNotification":
        return {}
    if action == "FirmwareStatusNotification":
        return {}
    if action == "LogStatusNotification":
        return {}
    if action == "ReservationStatusUpdate":
        return {}
    if action == "NotifyMonitoringReport":
        return {}
    if action == "ClearedChargingLimit":
        return {}
    if action == "ReportChargingProfiles":
        return {}
    if action == "NotifyEVChargingNeeds":
        return {"status": "Accepted"}
    if action == "NotifyChargingLimit":
        return {}
    if action == "DataTransfer":
        return {"status": "Accepted", "data": payload.get("data")}
    if action == "SignCertificate":
        return {"status": "Accepted"}
    if action == "Get15118EVCertificate":
        return {"status": "Failed"}

    return {}


def csms_call_v201(action: str, **kwargs: Any) -> dict[str, Any]:
    if action == "RequestStartTransaction":
        body: dict[str, Any] = {
            "idToken": {"idToken": kwargs.get("id_tag", "DEADBEEF"), "type": "ISO14443"},
            "remoteStartId": int(kwargs.get("remote_start_id", 1)),
        }
        if kwargs.get("evse_id") is not None:
            body["evseId"] = int(kwargs["evse_id"])
        return body
    if action == "RequestStopTransaction":
        return {"transactionId": str(kwargs["transaction_id"])}
    if action == "Reset":
        body = {"type": kwargs.get("reset_type", "Immediate")}
        if kwargs.get("evse_id") is not None:
            body["evseId"] = int(kwargs["evse_id"])
        return body
    if action == "UnlockConnector":
        return {"evseId": int(kwargs.get("evse_id", 1)), "connectorId": int(kwargs.get("connector_id", 1))}
    if action == "ChangeAvailability":
        body = {"operationalStatus": kwargs.get("operational_status", "Operative")}
        if kwargs.get("evse_id") is not None:
            body["evse"] = {"id": int(kwargs["evse_id"]), "connectorId": int(kwargs.get("connector_id", 1))}
        return body
    if action == "GetVariables":
        get_vars = kwargs.get("get_variables") or [
            {"component": {"name": "OCPPCommCtrlr"}, "variable": {"name": "HeartbeatInterval"}}
        ]
        return {"getVariableData": get_vars}
    if action == "SetVariables":
        set_vars = kwargs.get("set_variables") or [
            {
                "attributeValue": str(kwargs.get("value", "60")),
                "component": {"name": kwargs.get("component", "OCPPCommCtrlr")},
                "variable": {"name": kwargs.get("variable", "HeartbeatInterval")},
            }
        ]
        return {"setVariableData": set_vars}
    if action == "TriggerMessage":
        body = {"requestedMessage": kwargs.get("requested", "Heartbeat")}
        if kwargs.get("evse_id") is not None:
            body["evse"] = {"id": int(kwargs["evse_id"])}
        return body
    if action == "GetBaseReport":
        return {"requestId": int(kwargs.get("request_id", 1)), "reportBase": kwargs.get("report_base", "FullInventory")}
    if action == "ClearCache":
        return {}
    raise ValueError(f"unsupported CSMS action {action}")
