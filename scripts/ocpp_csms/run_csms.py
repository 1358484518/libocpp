#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Entry point: python3 scripts/ocpp_csms/run_csms.py --port 9000"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from server import main

if __name__ == "__main__":
    main()
