#!/usr/bin/env python3
"""
StratusScanCLI-Azure dependency bootstrap.

CloudShell-first: configure.py and azurescan.py call ensure_dependencies()
before importing utils, which pulls in Azure SDKs, pandas, and questionary.
This keeps a fresh Azure Cloud Shell run from requiring a manual pip step.

Stdlib-only. Safe to import before project dependencies are installed.
"""

import importlib
import os
import subprocess
import sys
from pathlib import Path

_ATTEMPTED_ENV = "AZURESCAN_BOOTSTRAP_ATTEMPTED"

_REQUIRED_MODULES = [
    "azure.identity",
    "azure.mgmt.resource.resources",
    "azure.mgmt.resource.subscriptions",
    "azure.mgmt.compute",
    "azure.mgmt.network",
    "azure.mgmt.storage",
    "pandas",
    "openpyxl",
    "dateutil",
    "questionary",
]


def _read_pyproject_dependencies() -> list[str]:
    pyproject = Path(__file__).parent / "pyproject.toml"
    try:
        import tomllib

        with open(pyproject, "rb") as fh:
            return tomllib.load(fh)["project"]["dependencies"]
    except ModuleNotFoundError:
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
    missing = [module for module in _REQUIRED_MODULES if _is_missing(module)]
    if not missing:
        return

    if os.environ.get(_ATTEMPTED_ENV):
        print(f"WARNING: dependencies still unavailable after install: {', '.join(missing)}")
        return

    print(f"Installing required dependencies (missing: {', '.join(missing)})...")
    deps = _read_pyproject_dependencies()
    subprocess.run([sys.executable, "-m", "pip", "install", *deps], check=True)
    print("Dependencies installed. Restarting...\n")

    os.environ[_ATTEMPTED_ENV] = "1"
    os.execv(sys.executable, [sys.executable, *sys.argv])
