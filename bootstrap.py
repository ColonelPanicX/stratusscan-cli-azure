#!/usr/bin/env python3
"""
StratusScanCLI-Azure — Dependency bootstrap.

CloudShell-first: the CLI entry points (azurescan.py, configure.py) call
ensure_dependencies() before importing utils, which pulls in the Azure SDKs
and pandas. This removes the manual `pip install` step from the quick start.

Stdlib-only — safe to import before any dependency is installed.
"""

import importlib
import os
import subprocess
import sys
from pathlib import Path

# Guards against an install loop if a package is still missing after install.
_ATTEMPTED_ENV = "AZURESCAN_BOOTSTRAP_ATTEMPTED"

# Representative modules — the exact submodules utils imports. We attempt a
# real import (not find_spec) because `azure` is a namespace package: a spec
# can resolve for azure.mgmt.resource while the client submodule is absent.
_REQUIRED_MODULES = [
    "azure.identity",
    "azure.mgmt.resource.resources",
    "azure.mgmt.resource.subscriptions",
    "azure.mgmt.costmanagement",
    "pandas",
    "openpyxl",
    "dateutil",
]


def _read_pyproject_dependencies() -> list:
    pyproject = Path(__file__).parent / "pyproject.toml"
    try:
        import tomllib  # Python 3.11+
        with open(pyproject, "rb") as f:
            return tomllib.load(f)["project"]["dependencies"]
    except ModuleNotFoundError:
        # Fallback for Python 3.9/3.10 (no tomllib): read the
        # dependencies = [ ... ] array literally.
        text = pyproject.read_text()
        start = text.index("dependencies = [")
        end = text.index("]", start)
        deps = []
        for line in text[start:end].splitlines()[1:]:
            line = line.strip().strip(",").strip()
            if line.startswith(('"', "'")):
                deps.append(line.strip("\"'"))
        return deps


def _is_missing(module: str) -> bool:
    try:
        importlib.import_module(module)
        return False
    except ImportError:
        return True


def ensure_dependencies() -> None:
    missing = [m for m in _REQUIRED_MODULES if _is_missing(m)]
    if not missing:
        return

    if os.environ.get(_ATTEMPTED_ENV):
        # Already installed once this session but something is still missing.
        # Don't loop — let the real import error surface downstream.
        print(f"WARNING: dependencies still unavailable after install: {', '.join(missing)}")
        return

    print(f"Installing required dependencies (missing: {', '.join(missing)})...")
    deps = _read_pyproject_dependencies()
    subprocess.run([sys.executable, "-m", "pip", "install", *deps], check=True)
    print("Dependencies installed. Restarting...\n")

    # Re-exec in a clean interpreter. Probing the imports above populated the
    # `azure` namespace package's cached __path__ before the packages existed;
    # a fresh process is the reliable way to pick up the new install.
    os.environ[_ATTEMPTED_ENV] = "1"
    os.execv(sys.executable, [sys.executable, *sys.argv])
