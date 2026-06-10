#!/usr/bin/env python3
"""
StratusScanCLI-Azure — Configuration Wizard
Version: v0.1.0

Handles subscription discovery and selection, environment configuration,
and writes config.json for use by azurescan.py and all exporter scripts.

Usage:
    python configure.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import bootstrap

bootstrap.ensure_dependencies()

try:
    import utils
except ImportError:
    print("ERROR: Could not import utils.py.")
    sys.exit(1)

utils.setup_logging("configure", log_to_file=True)
utils.log_script_start("configure.py", "AzureScan Configuration Wizard")

log = utils.get_logger()


# ---------------------------------------------------------------------------
# Environment selection
# ---------------------------------------------------------------------------

def select_environment() -> str:
    print("\n" + "=" * 64)
    print("  AZURE ENVIRONMENT SELECTION")
    print("=" * 64)
    print("  Select the Azure cloud environment for your credentials.")
    print()

    options = [
        "AzurePublicCloud   (commercial — portal.azure.com)",
        "AzureUSGovernment  (FedRAMP/government — portal.azure.us)",
    ]
    choice = utils.prompt_menu("ENVIRONMENT", options, allow_back=False, allow_exit=True)
    if choice == "exit":
        sys.exit(0)
    return "government" if choice == 2 else "public"


# ---------------------------------------------------------------------------
# Subscription discovery & selection
# ---------------------------------------------------------------------------

def discover_subscriptions() -> list:
    print("\nDiscovering accessible subscriptions...", end=" ", flush=True)
    try:
        subs = utils.list_subscriptions()
        print(f"found {len(subs)}.")
        return subs
    except Exception as exc:
        print(f"FAILED.\nError: {exc}")
        log.error("Subscription discovery failed: %s", exc)
        return []


def select_subscriptions(subs: list) -> list:
    if not subs:
        print("No accessible subscriptions found. Check your Azure credentials.")
        return []

    print("\n" + "=" * 64)
    print("  SUBSCRIPTION SELECTION")
    print("=" * 64)
    print("  Accessible subscriptions:\n")
    for i, sub in enumerate(subs, 1):
        state_label = f"  [{sub['state']}]" if sub.get("state") else ""
        print(f"  {i:3d}. {sub['name']}{state_label}")
        print(f"       {sub['id']}")
    print()

    options = [
        "Select a single subscription (set as default)",
        "Use all subscriptions",
        "Enter subscription ID manually",
    ]
    choice = utils.prompt_menu("SUBSCRIPTION", options, allow_back=False, allow_exit=True)
    if choice == "exit":
        sys.exit(0)

    if choice == 1:
        while True:
            try:
                raw = input(f"  Enter subscription number (1–{len(subs)}): ").strip()
                idx = int(raw) - 1
                if 0 <= idx < len(subs):
                    return [subs[idx]]
                print(f"  Invalid number. Enter 1–{len(subs)}.")
            except (ValueError, KeyboardInterrupt):
                print()
                return []

    if choice == 2:
        return subs

    if choice == 3:
        sub_id = input("  Enter subscription ID: ").strip()
        if sub_id:
            return [{"id": sub_id, "name": sub_id, "state": "Unknown", "tenant_id": ""}]
        return []

    return []


# ---------------------------------------------------------------------------
# Config write
# ---------------------------------------------------------------------------

def build_and_save_config(environment: str, selected_subs: list) -> dict:
    existing = utils.get_config()
    default_sub_id = selected_subs[0]["id"] if selected_subs else ""

    config = {
        **existing,
        "environment": environment,
        "subscriptions": selected_subs,
        "default_subscription_id": default_sub_id,
    }
    utils.save_config(config)
    return config


def _print_summary(config: dict) -> None:
    env_label = "AzureUSGovernment" if config["environment"] == "government" else "AzurePublicCloud"
    print("\n" + "=" * 64)
    print("  CONFIGURATION SAVED")
    print("=" * 64)
    print(f"  Environment:          {env_label}")
    print(f"  Default subscription: {config['default_subscription_id']}")
    print(f"  Subscriptions:        {len(config['subscriptions'])}")
    print()
    print("  Run azurescan.py to start exporting.")
    print("=" * 64 + "\n")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    print("\n" + "=" * 64)
    print("  StratusScanCLI-Azure — Configuration Wizard")
    print(f"  Version: {utils.get_version()}")
    print("=" * 64)
    print("  This wizard configures your Azure environment and subscription.")
    print()

    environment = select_environment()
    log.info("Environment selected: %s", environment)

    subs = discover_subscriptions()
    selected = select_subscriptions(subs)

    if not selected:
        print("No subscriptions selected. Configuration not saved.")
        return

    config = build_and_save_config(environment, selected)
    log.info(
        "Config saved — environment=%s, subscriptions=%d",
        environment,
        len(selected),
    )
    _print_summary(config)


if __name__ == "__main__":
    main()
