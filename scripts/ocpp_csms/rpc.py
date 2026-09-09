#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""OCPP-J CALL / CALLRESULT / CALLERROR helpers."""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any

CALL = 2
CALLRESULT = 3
CALLERROR = 4


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def new_message_id() -> str:
    return str(uuid.uuid4())


def make_call(action: str, payload: dict[str, Any], unique_id: str | None = None) -> list[Any]:
    return [CALL, unique_id or new_message_id(), action, payload]


def make_result(unique_id: str, payload: dict[str, Any]) -> list[Any]:
    return [CALLRESULT, unique_id, payload]


def make_error(
    unique_id: str,
    error_code: str = "InternalError",
    description: str = "",
    details: dict[str, Any] | None = None,
) -> list[Any]:
    return [CALLERROR, unique_id, error_code, description, details or {}]


def dumps(msg: list[Any]) -> str:
    return json.dumps(msg, separators=(",", ":"))


def loads(raw: str) -> list[Any]:
    data = json.loads(raw)
    if not isinstance(data, list) or len(data) < 2:
        raise ValueError("not an OCPP-J array")
    return data
