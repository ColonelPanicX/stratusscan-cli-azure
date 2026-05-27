#!/usr/bin/env python3
"""
StratusScanCLI-Azure — Dependency bootstrap.

CloudShell-first: the CLI entry points (azurescan.py, configure.py) call
ensure_dependencies() before importing utils, which pulls in the Azure SDKs
and pandas. This removes the manual `pip install` step from the quick start.

Stdlib-only — safe to import before any dependency is installed.
"""

import importlib.util
import subprocess
import sys
from pathlib import Path

# Representative modules — if any are missing, (re)install from pyproject.
_REQUIRED_MODULES = [
    "azure.identity",
    "azure.mgmt.resource",
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
    # find_spec raises (rather than returning None) when a parent package is
    # entirely absent, e.g. checking "azure.identity" when "azure" isn't there.
    try:
        return importlib.util.find_spec(module) is None
    except ModuleNotFoundError:
        return True


def ensure_dependencies() -> None:
    missing = [m for m in _REQUIRED_MODULES if _is_missing(m)]
    if not missing:
        return
    print("Installing required dependencies (first run, this may take a minute)...")
    deps = _read_pyproject_dependencies()
    subprocess.run([sys.executable, "-m", "pip", "install", *deps], check=True)
    print("Dependencies installed.\n")
