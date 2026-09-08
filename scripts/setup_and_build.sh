#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
# Bootstrap: check host, install deps, clone everest-cmake (+ libocpp if needed), build.
#
# Does NOT pip-install edm from github.com/EVerest/EVerest (that clones the whole
# monorepo and often fails behind a proxy). Uses scripts/edm_minimal.py instead.
#
# Usage (from repo root OR from this directory):
#   ./scripts/setup_and_build.sh
#   cd scripts && ./setup_and_build.sh
#
# GitHub unreachable / HTTP 502 from proxy:
#   GITHUB_MIRROR="https://ghproxy.net/" ./scripts/setup_and_build.sh
#   # clones become: https://ghproxy.net/https://github.com/org/repo.git
#
# Environment:
#   WORKSPACE_DIR   Default: $HOME/everest
#   GITHUB_MIRROR   Optional URL prefix for github.com clones (also used by CMake/CPM)
#   SKIP_APT=1      Do not apt-get install
#   SKIP_CLONE=1    Do not git clone / fetch
#   BUILD_TESTING=ON|OFF  Default: OFF

set -euo pipefail

log()  { printf '\n[\033[1;32mINFO\033[0m] %s\n' "$*"; }
warn() { printf '\n[\033[1;33mWARN\033[0m] %s\n' "$*"; }
err()  { printf '\n[\033[1;31mERROR\033[0m] %s\n' "$*" >&2; }
die()  { err "$*"; exit 1; }

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_CANDIDATE="$(cd "${SCRIPT_DIR}/.." && pwd)"

WORKSPACE_DIR="${WORKSPACE_DIR:-${HOME}/everest}"
BUILD_TYPE="${BUILD_TYPE:-Debug}"
JOBS="${JOBS:-$(nproc 2>/dev/null || echo 4)}"
BUILD_TESTING="${BUILD_TESTING:-OFF}"
SKIP_APT="${SKIP_APT:-0}"
SKIP_CLONE="${SKIP_CLONE:-0}"
GITHUB_MIRROR="${GITHUB_MIRROR:-}"

LIBOCPP_GIT="${LIBOCPP_GIT:-https://github.com/EVerest/libocpp.git}"
EVEREST_CMAKE_GIT="${EVEREST_CMAKE_GIT:-https://github.com/EVerest/everest-cmake.git}"

is_libocpp_tree() {
    local d="$1"
    [[ -f "${d}/CMakeLists.txt" ]] && grep -q 'project(ocpp' "${d}/CMakeLists.txt"
}

need_cmd() { command -v "$1" >/dev/null 2>&1; }

mirror_url() {
    local url="$1"
    if [[ -z "${GITHUB_MIRROR}" ]]; then
        printf '%s\n' "$url"
        return
    fi
    printf '%s/%s\n' "${GITHUB_MIRROR%/}" "$url"
}

git_clone_retry() {
    local url="$1" dest="$2"
    local mirrored
    mirrored="$(mirror_url "$url")"
    local i
    for i in 1 2 3; do
        log "git clone (try ${i}/3): ${mirrored} -> ${dest}"
        if git clone --depth 1 "${mirrored}" "${dest}"; then
            return 0
        fi
        warn "clone failed (try ${i})"
        rm -rf "${dest}"
        sleep $((i * 2))
    done
    die "git clone failed after 3 tries: ${mirrored}
If you see HTTP 502 from proxy, GitHub is blocked or the proxy is broken.
Retry with a mirror, for example:
  GITHUB_MIRROR=https://ghproxy.net/ $0
Or fix HTTPS_PROXY / clone everest-cmake + libocpp by hand, then SKIP_CLONE=1."
}

setup_github_git_insteadOf() {
    [[ -z "${GITHUB_MIRROR}" ]] && return 0
    local instead="${GITHUB_MIRROR%/}/https://github.com/"
    local cfg="${WORKSPACE_DIR}/.gitconfig-github-mirror"
    mkdir -p "${WORKSPACE_DIR}"
    git config --file "${cfg}" --unset-all "url.${instead}.insteadof" 2>/dev/null || true
    git config --file "${cfg}" --add "url.${instead}.insteadof" "https://github.com/"
    export GIT_CONFIG_GLOBAL="${cfg}"
    export GIT_CONFIG_COUNT=1
    export GIT_CONFIG_KEY_0="url.${instead}.insteadof"
    export GIT_CONFIG_VALUE_0="https://github.com/"
    export GIT_CONFIG_PARAMETERS="url.${instead}.insteadof=${GIT_CONFIG_VALUE_0}"
    export GITHUB_MIRROR
    log "Git insteadOf: https://github.com/ -> ${instead}"
    log "edm/CPM git URLs will be rewritten via GITHUB_MIRROR=${GITHUB_MIRROR}"
}

github_reachable() {
    if command -v timeout >/dev/null 2>&1; then
        GIT_TERMINAL_PROMPT=0 timeout 12 git ls-remote --heads https://github.com/EVerest/libevse-security.git HEAD >/dev/null 2>&1
    else
        GIT_TERMINAL_PROMPT=0 git ls-remote --heads https://github.com/EVerest/libevse-security.git HEAD >/dev/null 2>&1
    fi
}

maybe_auto_github_mirror() {
    if [[ -n "${GITHUB_MIRROR}" ]]; then
        return 0
    fi
    if [[ "${AUTO_GITHUB_MIRROR:-1}" != "1" ]]; then
        return 0
    fi
    log "Probing github.com (timeout 12s)..."
    if github_reachable; then
        log "github.com reachable; not using a mirror"
        return 0
    fi
    GITHUB_MIRROR="${GITHUB_MIRROR_DEFAULT:-https://ghproxy.net/}"
    warn "github.com failed (proxy 502 / timeout). Auto GITHUB_MIRROR=${GITHUB_MIRROR}"
    warn "Override: GITHUB_MIRROR=https://your-mirror/  or AUTO_GITHUB_MIRROR=0"
}

# ---------------------------------------------------------------------------
log "1/5 Checking host environment"

if [[ "$(uname -s)" != "Linux" ]]; then
    die "This script targets Linux (Debian/Ubuntu or WSL). Current OS: $(uname -s)"
fi

if [[ -f /etc/os-release ]]; then
    # shellcheck disable=SC1091
    . /etc/os-release
    log "OS: ${PRETTY_NAME:-$ID}"
    case "${ID:-}" in
        ubuntu|debian|linuxmint|pop) ;;
        *)
            warn "Untested distro '${ID}'. apt-based install may fail; set SKIP_APT=1."
            ;;
    esac
fi

log "Kernel: $(uname -r)  Arch: $(uname -m)"
if [[ -n "${https_proxy:-}${HTTPS_PROXY:-}${http_proxy:-}${HTTP_PROXY:-}" ]]; then
    log "Proxy: HTTPS_PROXY=${HTTPS_PROXY:-${https_proxy:-}} HTTP_PROXY=${HTTP_PROXY:-${http_proxy:-}}"
fi
need_cmd python3 || die "python3 is required"
log "python3: $(python3 --version 2>&1)"

# ---------------------------------------------------------------------------
log "2/5 Installing system packages"

APT_PACKAGES=(
    build-essential
    g++
    cmake
    git
    pkg-config
    python3
    python3-yaml
    libboost-all-dev
    libsqlite3-dev
    libssl-dev
)

pkg_missing() { ! dpkg -s "$1" >/dev/null 2>&1; }

if [[ "${SKIP_APT}" == "1" ]]; then
    warn "SKIP_APT=1 — not installing apt packages"
else
    need_cmd apt-get || die "apt-get not found. Install deps manually, then SKIP_APT=1."
    missing=()
    for p in "${APT_PACKAGES[@]}"; do
        if pkg_missing "$p"; then
            missing+=("$p")
        fi
    done
    if [[ ${#missing[@]} -eq 0 ]]; then
        log "All apt packages already installed"
    else
        log "Need to install: ${missing[*]}"
        SUDO=""
        if [[ "$(id -u)" -ne 0 ]]; then
            need_cmd sudo || die "Need root or sudo to apt-get install"
            SUDO="sudo"
        fi
        export DEBIAN_FRONTEND=noninteractive
        ${SUDO} apt-get update
        ${SUDO} apt-get install -y "${missing[@]}"
    fi
fi

need_cmd git || die "git still missing"
need_cmd cmake || die "cmake still missing"
need_cmd g++ || die "g++ still missing"
python3 -c "import yaml" || die "python3-yaml missing (PyYAML). Install python3-yaml."

log "cmake $(cmake --version | head -n1)"
log "g++ $(g++ --version | head -n1)"
pkg-config --exists sqlite3 || die "SQLite3 dev files not found (libsqlite3-dev)"
log "SQLite $(pkg-config --modversion sqlite3)"
log "OpenSSL $(openssl version 2>/dev/null || echo unknown)"

maybe_auto_github_mirror
setup_github_git_insteadOf

# ---------------------------------------------------------------------------
log "3/5 Cloning / locating source trees"

LIBOCPP_SRC=""
if is_libocpp_tree "${REPO_CANDIDATE}"; then
    LIBOCPP_SRC="${REPO_CANDIDATE}"
    log "Using libocpp tree that contains this script: ${LIBOCPP_SRC}"
elif is_libocpp_tree "$(pwd)"; then
    LIBOCPP_SRC="$(pwd)"
    log "Using current directory as libocpp: ${LIBOCPP_SRC}"
fi

if [[ -z "${LIBOCPP_SRC}" ]]; then
    mkdir -p "${WORKSPACE_DIR}"
    LIBOCPP_SRC="${WORKSPACE_DIR}/libocpp"
    if [[ "${SKIP_CLONE}" == "1" ]]; then
        is_libocpp_tree "${LIBOCPP_SRC}" || die "SKIP_CLONE=1 but ${LIBOCPP_SRC} is not a libocpp tree"
    elif [[ -d "${LIBOCPP_SRC}/.git" ]]; then
        log "libocpp already cloned"
    else
        git_clone_retry "${LIBOCPP_GIT}" "${LIBOCPP_SRC}"
    fi
fi

if [[ -z "${EVEREST_CMAKE_DIR:-}" ]]; then
    _ocpp_parent="$(cd "${LIBOCPP_SRC}/.." && pwd)"
    if [[ "${_ocpp_parent}" == "/" ]] || [[ ! -w "${_ocpp_parent}" ]]; then
        mkdir -p "${WORKSPACE_DIR}"
        EVEREST_CMAKE_DIR="${WORKSPACE_DIR}/everest-cmake"
        log "libocpp parent is not writable (${_ocpp_parent}); everest-cmake -> ${EVEREST_CMAKE_DIR}"
    else
        EVEREST_CMAKE_DIR="${_ocpp_parent}/everest-cmake"
    fi
fi
if [[ "${SKIP_CLONE}" == "1" ]]; then
    [[ -f "${EVEREST_CMAKE_DIR}/everest-cmake-config.cmake" ]] || die "SKIP_CLONE=1 but everest-cmake not at ${EVEREST_CMAKE_DIR}"
elif [[ -d "${EVEREST_CMAKE_DIR}/.git" ]] || [[ -f "${EVEREST_CMAKE_DIR}/everest-cmake-config.cmake" ]]; then
    log "everest-cmake present at ${EVEREST_CMAKE_DIR}"
else
    git_clone_retry "${EVEREST_CMAKE_GIT}" "${EVEREST_CMAKE_DIR}"
fi

[[ -f "${EVEREST_CMAKE_DIR}/everest-cmake-config.cmake" ]] || die "everest-cmake-config.cmake missing in ${EVEREST_CMAKE_DIR}"

# ---------------------------------------------------------------------------
log "4/5 Installing local edm stub (no EVerest monorepo clone)"

EDM_PY="${LIBOCPP_SRC}/scripts/edm_minimal.py"
[[ -f "${EDM_PY}" ]] || die "missing ${EDM_PY}"
EDM_BIN_DIR="${WORKSPACE_DIR}/bin"
mkdir -p "${EDM_BIN_DIR}"
cat > "${EDM_BIN_DIR}/edm" << EOF
#!/usr/bin/env bash
export GITHUB_MIRROR="${GITHUB_MIRROR}"
exec python3 "${EDM_PY}" "\$@"
EOF
chmod +x "${EDM_BIN_DIR}/edm"
export PATH="${EDM_BIN_DIR}:${PATH}"
export GITHUB_MIRROR
edm --version || die "edm stub not runnable"
log "Using $(command -v edm)  ($(edm --version))"

BUILD_DIR="${BUILD_DIR:-${LIBOCPP_SRC}/build}"
INSTALL_PREFIX="${INSTALL_PREFIX:-${LIBOCPP_SRC}/dist}"

# Failed FetchContent stamps keep retrying the old github.com URL.
if [[ -n "${GITHUB_MIRROR}" ]] && [[ -d "${BUILD_DIR}" ]]; then
    warn "GITHUB_MIRROR set: clearing ${BUILD_DIR} CMake cache/_deps so CPM reclones via mirror"
    rm -rf "${BUILD_DIR}/CMakeCache.txt" "${BUILD_DIR}/CMakeFiles" "${BUILD_DIR}/_deps" \
        "${BUILD_DIR}/dependencies.cmake"
fi

# ---------------------------------------------------------------------------
log "5/5 Configuring and compiling (examples ON, testing ${BUILD_TESTING})"

cmake -S "${LIBOCPP_SRC}" -B "${BUILD_DIR}" \
    -DCMAKE_BUILD_TYPE="${BUILD_TYPE}" \
    -DCMAKE_C_COMPILER="${CC:-/usr/bin/gcc}" \
    -DCMAKE_CXX_COMPILER="${CXX:-/usr/bin/g++}" \
    -DCMAKE_INSTALL_PREFIX="${INSTALL_PREFIX}" \
    -Deverest-cmake_DIR="${EVEREST_CMAKE_DIR}" \
    -DLIBOCPP16_BUILD_EXAMPLES=ON \
    -DBUILD_TESTING="${BUILD_TESTING}"

cmake --build "${BUILD_DIR}" -j"${JOBS}" --target charge_point ocpp

CHARGE_POINT=""
if [[ -x "${BUILD_DIR}/src/charge_point" ]]; then
    CHARGE_POINT="${BUILD_DIR}/src/charge_point"
elif [[ -x "${BUILD_DIR}/charge_point" ]]; then
    CHARGE_POINT="${BUILD_DIR}/charge_point"
fi

log "Build finished"
echo "  libocpp source : ${LIBOCPP_SRC}"
echo "  everest-cmake  : ${EVEREST_CMAKE_DIR}"
echo "  build dir      : ${BUILD_DIR}"
if [[ -n "${CHARGE_POINT}" ]]; then
    echo "  example binary : ${CHARGE_POINT}"
else
    warn "charge_point binary not found; check cmake --build output"
fi
echo
echo "Reconfigure later with edm on PATH:"
echo "  export PATH=\"${EDM_BIN_DIR}:\$PATH\""
if [[ -n "${GITHUB_MIRROR}" ]]; then
    echo "  export GITHUB_MIRROR=\"${GITHUB_MIRROR}\""
fi
