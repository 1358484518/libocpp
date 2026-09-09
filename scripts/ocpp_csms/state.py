#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""In-memory CSMS session state for one charge point."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ChargePointState:
    cp_id: str
    protocol: str  # ocpp1.6 | ocpp2.0.1
    websocket: Any = None
    boot_payload: dict[str, Any] = field(default_factory=dict)
    connectors: dict[int, str] = field(default_factory=dict)
    last_heartbeat: str | None = None
    # 1.6 numeric transaction ids / 2.0.1 string transaction ids
    next_tx_numeric: int = 1
    active_tx: dict[str, Any] = field(default_factory=dict)
    id_tags: dict[str, str] = field(default_factory=lambda: {"DEADBEEF": "Accepted", "TESTTAG": "Accepted"})
    config: dict[str, str] = field(
        default_factory=lambda: {
            "HeartbeatInterval": "60",
            "MeterValueSampleInterval": "10",
            "NumberOfConnectors": "1",
            "AuthorizeRemoteTxRequests": "false",
        }
    )
    variables: dict[tuple[str, str], str] = field(
        default_factory=lambda: {
            ("OCPPCommCtrlr", "HeartbeatInterval"): "60",
            ("AuthCtrlr", "Enabled"): "true",
            ("TxCtrlr", "EVConnectionTimeOut"): "30",
        }
    )
    log: list[tuple[str, str, Any]] = field(default_factory=list)

    def record(self, direction: str, action: str, payload: Any) -> None:
        self.log.append((direction, action, payload))
