#!/usr/bin/env python3
"""
StratusScanCLI-Azure dependency bootstrap.

CloudShell-first: stratusscan.py and configure.py call ensure_dependencies()
from main() before any Azure SDK, pandas or openpyxl import happens. This keeps
a fresh Azure Cloud Shell run from requiring a manual pip step.

Every dependency in pyproject.toml is probed by distribution metadata, so a
partial install is detected without importing anything. Stdlib-only. Safe to
import before project dependencies are installed.
"""

import os
import re
import subprocess
import sys
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

_ATTEMPTED_ENV = "STRATUSSCAN_BOOTSTRAP_ATTEMPTED"
EXIT_CONFIG = 2

_DIST_NAME = re.compile(r"^\s*([A-Za-z0-9][A-Za-z0-9._-]*)")


def _read_pyproject_dependencies() -> list[str]:
    pyproject = Path(__file__).parent / "pyproject.toml"
    try:
        import tomllib
    except ModuleNotFoundError:
        return _parse_dependencies_without_tomllib(pyproject.read_text(encoding="utf-8"))

    with open(pyproject, "rb") as fh:
        return tomllib.load(fh)["project"]["dependencies"]


def _parse_dependencies_without_tomllib(text: str) -> list[str]:
    """Python 3.10 has no tomllib; read the `dependencies = [...]` array by line.

    Handles comment lines, trailing comments, trailing commas and extras like
    `pkg[extra]>=1`. Anything more exotic belongs in tomllib.
    """
    lines = iter(text.splitlines())
    for line in lines:
        if line.strip().startswith("dependencies = ["):
            break
    else:
        raise ValueError("pyproject.toml has no [project] dependencies array")

    deps = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("]"):
            return deps
        if not stripped or stripped.startswith("#"):
            continue
        match = re.match(r"""^(["'])(.*?)\1""", stripped)
        if match:
            deps.append(match.group(2))
    raise ValueError("pyproject.toml dependencies array is not closed")


def _distribution_name(requirement: str) -> str:
    match = _DIST_NAME.match(requirement)
    if not match:
        raise ValueError(f"Cannot read a distribution name from requirement {requirement!r}")
    return match.group(1)


def _is_missing(requirement: str) -> bool:
    try:
        version(_distribution_name(requirement))
        return False
    except PackageNotFoundError:
        return True


def missing_dependencies(deps: list[str]) -> list[str]:
    return [dep for dep in deps if _is_missing(dep)]


def ensure_dependencies() -> None:
    deps = _read_pyproject_dependencies()
    missing = missing_dependencies(deps)
    if not missing:
        return

    names = ", ".join(_distribution_name(dep) for dep in missing)
    if os.environ.get(_ATTEMPTED_ENV):
        print(f"WARNING: dependencies still unavailable after install: {names}")
        return

    print(f"Installing required dependencies (missing: {names})...")
    try:
        subprocess.run([sys.executable, "-m", "pip", "install", "--quiet", *deps], check=True)
    except subprocess.CalledProcessError as exc:
        print(f"ERROR: pip install exited {exc.returncode} — dependencies not installed. Check network access and rerun.")
        sys.exit(EXIT_CONFIG)
    print("Dependencies installed. Restarting...\n")

    os.environ[_ATTEMPTED_ENV] = "1"
    os.execv(sys.executable, [sys.executable, *sys.argv])
