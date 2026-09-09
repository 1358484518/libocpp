#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
# Start DDD on the OCPP 1.6 example, args pre-set, breakpoint on main.
#
# DDD 3.3.x does not support: ddd --gdb --args ./charge_point ...
# Use this script instead (same as: ddd ./charge_point  then set args).
#
# Usage (from repo root or any cwd):
#   ./scripts/debug_charge_point_ddd.sh
#
# Another terminal first:
#   python3 scripts/ocpp_csms/run_csms.py --port 9000
# Do not enable HTTP(S) proxy.
#
# After DDD opens: Program → Run  (or type: run)
# You should stop in main() of src/charge_point.cpp.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "${SCRIPT_DIR}/.." && pwd)"

BIN="${CHARGE_POINT_BIN:-${REPO}/build/src/charge_point}"
CONF="${REPO}/scripts/ocpp_csms/config-mock-v16.json"
SHARE="${REPO}/config/v16"
LOGCONF="${REPO}/config/logging.ini"

if [[ ! -x "${BIN}" ]]; then
    echo "Missing executable: ${BIN}" >&2
    echo "Build Debug first: ./scripts/setup_and_build.sh" >&2
    exit 1
fi
if [[ ! -f "${CONF}" ]]; then
    echo "Missing config: ${CONF}" >&2
    exit 1
fi
if ! command -v ddd >/dev/null 2>&1; then
    echo "ddd not found. Install: sudo apt install ddd" >&2
    echo "Or use gdb: gdb -x /tmp/libocpp-charge_point.gdb" >&2
    exit 1
fi
if [[ -z "${DISPLAY:-}" ]]; then
    echo "DISPLAY is empty; DDD needs a graphical session." >&2
    exit 1
fi

GDBFILE="${TMPDIR:-/tmp}/libocpp-charge_point.gdb"
cat > "${GDBFILE}" << EOF
set pagination off
directory ${REPO}
directory ${REPO}/src
directory ${REPO}/lib
directory ${REPO}/include
file ${BIN}
set args --share-path ${SHARE} --conf ${CONF} --logconf ${LOGCONF}
break main
EOF

echo "Repo: ${REPO}"
echo "Binary: ${BIN}"
echo "GDB commands: ${GDBFILE}"
echo
echo "Start CSMS in another terminal (no HTTP proxy):"
echo "  python3 ${REPO}/scripts/ocpp_csms/run_csms.py --port 9000"
echo
echo "DDD: when the window appears, Program → Run  (stops in main)."
echo "Then: next / step / continue. Extra breaks e.g.:"
echo "  break ocpp::v16::ChargePointImpl::boot_notification"
echo

cd "${REPO}"
# Do not pass --args to ddd (breaks DDD 3.3 GUI). Hand the program only.
# -x is for gdb inside --debugger.
exec ddd --debugger "gdb -q -x ${GDBFILE}" "${BIN}"
