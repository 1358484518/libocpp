#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Minimal edm stand-in so libocpp can configure without cloning EVerest/EVerest.

Implements:
  edm --version
  edm --cmake --working_dir DIR --out FILE
  edm release --everest-dir DIR --build-dir DIR --out FILE
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

try:
    import yaml
except ImportError:
    print("edm: need PyYAML (apt package python3-yaml)", file=sys.stderr)
    sys.exit(1)


def mirror_git_url(url: str) -> str:
    """Prefix github.com URLs so CPM/git do not CONNECT to github through a broken proxy."""
    mirror = os.environ.get("GITHUB_MIRROR", "").strip().rstrip("/")
    if not mirror or not url:
        return url
    if url.startswith("https://github.com/"):
        return f"{mirror}/{url}"
    return url


def emit_cmake(working_dir: Path, out: Path) -> None:
    deps_file = working_dir / "dependencies.yaml"
    workspace = os.environ.get("EVEREST_EDM_WORKSPACE") or str(working_dir.parent)
    lines = [
        f"set(ENV{{EVEREST_EDM_WORKSPACE}} {workspace})",
        "set(CPM_USE_NAMED_CACHE_DIRECTORIES ON)",
    ]
    if deps_file.is_file():
        data = yaml.safe_load(deps_file.read_text(encoding="utf-8")) or {}
        if not isinstance(data, dict):
            data = {}
        for name, spec in data.items():
            if not isinstance(spec, dict):
                continue
            git = mirror_git_url(spec.get("git") or "")
            tag = spec.get("git_tag")
            if not git:
                continue
            opts = spec.get("options") or []
            if isinstance(opts, str):
                opts = [opts]
            opt_str = " ".join(f'"{o}"' for o in opts)
            cond = spec.get("cmake_condition")
            lines.append(f'if("{name}" IN_LIST EVEREST_EXCLUDE_DEPENDENCIES)')
            lines.append(f'    message(STATUS "Excluding dependency {name}")')
            if cond:
                lines.append(f"elseif({cond})")
            else:
                lines.append("else()")
            lines.append("CPMAddPackage(")
            lines.append(f"    NAME {name}")
            lines.append(f"    GIT_REPOSITORY {git}")
            if tag:
                lines.append(f"    GIT_TAG {tag}")
            if opt_str:
                lines.append("    OPTIONS")
                lines.append(f"        {opt_str}")
            lines.append(")")
            if cond:
                lines.append("else()")
                lines.append(
                    f'    message(STATUS "Excluding dependency {name} based on cmake_condition")'
                )
            lines.append("endif()")
            lines.append("")
    lines.append("")
    lines.append("execute_process(")
    lines.append(
        '    COMMAND "${EVEREST_DEPENDENCY_MANAGER}" release '
        "--everest-dir ${PROJECT_SOURCE_DIR} --build-dir ${CMAKE_BINARY_DIR} "
        "--out ${CMAKE_BINARY_DIR}/release.json"
    )
    lines.append(")")
    lines.append("")
    lines.append("install(")
    lines.append('    FILES "${CMAKE_BINARY_DIR}/release.json"')
    lines.append('    DESTINATION "${CMAKE_INSTALL_SYSCONFDIR}/everest"')
    lines.append(")")
    lines.append("")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")


def emit_release(out: Path) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"edm": "minimal-stub", "version": "0.0.0"}) + "\n")


def main(argv: list[str]) -> int:
    if "--version" in argv or (len(argv) == 2 and argv[1] in ("-V", "-v")):
        print("edm 0.0.0-libocpp-stub")
        return 0

    parser = argparse.ArgumentParser(prog="edm", add_help=True)
    parser.add_argument("--cmake", action="store_true")
    parser.add_argument("--working_dir")
    parser.add_argument("--out")
    parser.add_argument("--everest-dir")
    parser.add_argument("--build-dir")
    parser.add_argument("command", nargs="?")
    args, _unknown = parser.parse_known_args(argv[1:])

    if args.cmake:
        if not args.working_dir or not args.out:
            print("edm --cmake requires --working_dir and --out", file=sys.stderr)
            return 2
        emit_cmake(Path(args.working_dir), Path(args.out))
        return 0

    if args.command == "release":
        if not args.out:
            print("edm release requires --out", file=sys.stderr)
            return 2
        emit_release(Path(args.out))
        return 0

    print("edm 0.0.0-libocpp-stub")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
