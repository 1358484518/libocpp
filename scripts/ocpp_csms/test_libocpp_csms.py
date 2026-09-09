#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Drive libocpp C++ charge_point / charge_point_v2 against the Python CSMS.

Set CHARGE_POINT_BIN and CHARGE_POINT_V2_BIN, or pass --bin / --bin-v2.
Share path defaults to <repo>/config/v16 for the 1.6 example.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from server import serve

REPO = Path(__file__).resolve().parents[2]


def _default_bin(name: str) -> str | None:
    env = os.environ.get("CHARGE_POINT_BIN" if name == "charge_point" else "CHARGE_POINT_V2_BIN")
    if env and Path(env).is_file():
        return env
    for p in (
        Path("/tmp/libocpp-build/src") / name,
        Path("/tmp/user-libocpp/build/src") / name,
        REPO / "build" / "src" / name,
    ):
        if p.is_file():
            return str(p)
    return None


class LibocppAgainstCsmsTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.ws_server, self.csms, self.base_uri = await serve("127.0.0.1", 0)
        self.port = int(self.base_uri.rsplit(":", 1)[1])
        self.addAsyncCleanup(self._stop)

    async def _stop(self) -> None:
        self.ws_server.close()
        await self.ws_server.wait_closed()

    async def test_libocpp_v16_auto_session(self) -> None:
        binary = _default_bin("charge_point")
        if not binary:
            self.skipTest("charge_point binary not built (LIBOCPP16_BUILD_EXAMPLES=ON)")
        share = REPO / "config" / "v16"
        cfg = json.loads((Path(__file__).parent / "config-mock-v16.json").read_text())
        cfg["Internal"]["CentralSystemURI"] = f"127.0.0.1:{self.port}/"
        cfg["Internal"]["ChargePointId"] = "cp001"
        work = Path(tempfile.mkdtemp(prefix="libocpp16-"))
        conf_path = work / "config.json"
        conf_path.write_text(json.dumps(cfg))
        proc = await asyncio.create_subprocess_exec(
            binary,
            "--share-path",
            str(share),
            "--conf",
            str(conf_path),
            "--logconf",
            str(REPO / "config" / "logging.ini"),
            "--database-path",
            str(work / "db"),
            "--user-config",
            str(work / "user_config.json"),
            "--auto-session",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        try:
            out, _ = await asyncio.wait_for(proc.communicate(), timeout=40)
        except asyncio.TimeoutError:
            proc.kill()
            self.fail("libocpp v16 auto-session timed out")
        log = out.decode(errors="replace")
        self.assertEqual(proc.returncode, 0, log)
        st = self.csms.get("cp001")
        self.assertIsNotNone(st, log)
        actions = [a for d, a, _ in st.log if d == "cp->csms"]
        self.assertIn("BootNotification", actions, log)
        self.assertIn("StartTransaction", actions, log)
        self.assertIn("StopTransaction", actions, log)

    async def test_libocpp_v201_auto_session(self) -> None:
        binary = _default_bin("charge_point_v2")
        if not binary:
            self.skipTest("charge_point_v2 binary not built (LIBOCPP16_BUILD_EXAMPLES=ON)")
        import shutil

        cfg_root = Path(tempfile.mkdtemp(prefix="ocpp201-cfg-"))
        shutil.copytree(REPO / "config" / "v2" / "component_config", cfg_root / "component_config")
        internal = cfg_root / "component_config" / "standardized" / "InternalCtrlr.json"
        text = internal.read_text()
        text = text.replace("ws://localhost:9000", f"ws://127.0.0.1:{self.port}")
        internal.write_text(text)
        proc = await asyncio.create_subprocess_exec(
            binary,
            "--config-dir",
            str(cfg_root / "component_config"),
            "--migrations",
            str(REPO / "config" / "v2" / "device_model_migrations"),
            "--core-migrations",
            str(REPO / "config" / "v2" / "core_migrations"),
            "--logconf",
            str(REPO / "config" / "logging.ini"),
            "--db-dir",
            str(tempfile.mkdtemp(prefix="libocpp201-db-")),
            "--auto-session",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        try:
            out, _ = await asyncio.wait_for(proc.communicate(), timeout=60)
        except asyncio.TimeoutError:
            proc.kill()
            self.fail("libocpp v2 auto-session timed out")
        log = out.decode(errors="replace")
        self.assertEqual(proc.returncode, 0, log)
        st = self.csms.get("cp001")
        self.assertIsNotNone(st, log)
        actions = [a for d, a, _ in st.log if d == "cp->csms"]
        self.assertIn("BootNotification", actions, log)
        self.assertIn("TransactionEvent", actions, log)


if __name__ == "__main__":
    unittest.main()
