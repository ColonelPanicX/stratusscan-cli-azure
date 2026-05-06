#!/usr/bin/env python3
"""
StratusScan-Azure — main menu.

Lightweight launcher that subprocesses individual exporter scripts. Mirrors
the pattern used by stratusscan.py in the AWS-side project.

Cloud Shell quickstart:
    git clone <repo>
    cd StratusScan-Azure
    pip install --user -r <(python -c "import tomllib,sys; \
        d=tomllib.load(open('pyproject.toml','rb')); \
        print('\\n'.join(d['project']['dependencies']))")
    python stratusscan_azure.py
"""

import os
import subprocess
import sys
from pathlib import Path

_root = Path(__file__).parent.absolute()
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))


REQUIRED_PACKAGES = [
    ("azure.identity", "azure-identity"),
    ("azure.mgmt.resource", "azure-mgmt-resource<25"),
    ("azure.mgmt.subscription", "azure-mgmt-subscription"),
    ("azure.mgmt.resourcegraph", "azure-mgmt-resourcegraph"),
    ("azure.mgmt.authorization", "azure-mgmt-authorization"),
    ("azure.mgmt.policyinsights", "azure-mgmt-policyinsights"),
    ("pandas", "pandas"),
    ("openpyxl", "openpyxl"),
    ("requests", "requests"),
]


def check_dependencies() -> bool:
    missing = []
    for module, package in REQUIRED_PACKAGES:
        try:
            __import__(module)
        except ImportError:
            missing.append(package)

    if not missing:
        return True

    print("Missing Python packages:")
    for p in missing:
        print(f"  • {p}")

    answer = input("\nInstall them now with `pip install --user`? [Y/n]: ").strip().lower()
    if answer in ("", "y", "yes"):
        cmd = [sys.executable, "-m", "pip", "install", "--user", *missing]
        result = subprocess.run(cmd)
        return result.returncode == 0

    print("Install them manually before running again.")
    return False


def print_box(title: str, width: int = 70) -> None:
    print("╔" + "═" * (width - 2) + "╗")
    pad = (width - len(title) - 2) // 2
    print("║" + " " * pad + title + " " * (width - len(title) - pad - 2) + "║")
    print("╚" + "═" * (width - 2) + "╝")


def print_section(title: str, width: int = 70) -> None:
    print("\n" + "═" * width)
    print(title)
    print("═" * width)


def print_header() -> None:
    from sslib.cloud import detect_cloud

    cloud = detect_cloud()
    print_box("STRATUSSCAN-AZURE", 70)
    print(f"  Cloud: {cloud['name']}")
    in_cs = "ACC_CLOUD" in os.environ
    print(f"  Cloud Shell: {'yes' if in_cs else 'no'}")

    config_path = _root / "config.json"
    print(f"  Config: {'loaded' if config_path.exists() else 'not configured — run [0]'}")


SCRIPTS_DIR = _root / "scripts"

MENU = {
    "0": ("Configure StratusScan-Azure", _root / "configure.py"),
    "1": ("Resource Graph (full inventory)", SCRIPTS_DIR / "resource_graph_export.py"),
    "2": ("Microsoft Entra ID (users, groups, apps)", SCRIPTS_DIR / "entra_id_export.py"),
    "3": ("Azure RBAC (role assignments + custom roles)", SCRIPTS_DIR / "rbac_export.py"),
    "4": ("Azure Policy (assignments + compliance)", SCRIPTS_DIR / "policy_export.py"),
    "5": ("Run all exporters", None),
}


def execute_script(script: Path) -> int:
    if not script.exists():
        print(f"  ERROR: script not found: {script}")
        return 1
    return subprocess.call([sys.executable, str(script)])


def run_all() -> int:
    rc = 0
    for key in ("1", "2", "3", "4"):
        name, script = MENU[key]
        print_section(name.upper())
        rc |= execute_script(script)
    return rc


def display_main_menu() -> None:
    print_header()
    print_section("MAIN MENU")
    for key, (name, _script) in MENU.items():
        print(f"  [{key}] {name}")
    print("\n" + "─" * 70)
    print("  q = quit")
    print("─" * 70)


def main() -> int:
    if not check_dependencies():
        return 1

    while True:
        display_main_menu()
        choice = input("\n> ").strip().lower()

        if choice == "q":
            return 0
        if choice not in MENU:
            print("Invalid selection.")
            continue

        name, script = MENU[choice]
        if choice == "5":
            run_all()
        elif script is not None:
            execute_script(script)
        input("\nPress Enter to continue...")


if __name__ == "__main__":
    try:
        sys.exit(main() or 0)
    except KeyboardInterrupt:
        print("\nExiting.")
        sys.exit(130)
