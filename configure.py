#!/usr/bin/env python3
"""
StratusScanCLI-Azure — Configuration Wizard
Version: v0.1.0

Handles subscription discovery and selection, environment configuration,
and writes config.json for use by stratusscan.py and all exporter scripts.

Usage:
    python configure.py
    python configure.py --show
    python configure.py --validate
    python configure.py --environment government --subscriptions ID,ID --default ID
"""

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import bootstrap

try:
    import cli_ui
    import utils
except ImportError:
    print("ERROR: Could not import utils.py.")
    sys.exit(1)

log = utils.get_logger()

ENVIRONMENT_CHOICES = ("public", "government", "auto")


def _env_label(environment: str) -> str:
    return "AzureUSGovernment" if environment == "government" else "AzurePublicCloud"


# ---------------------------------------------------------------------------
# Environment selection
# ---------------------------------------------------------------------------

def select_environment() -> str:
    if utils.is_auto_run():
        return utils.detect_environment()

    print("\n" + "=" * 64)
    print("  AZURE ENVIRONMENT SELECTION")
    print("=" * 64)
    print("  Select the Azure cloud environment for your credentials.")

    detected = utils.detect_azure_cloud()
    if detected:
        print(f"  Detected active Azure CLI cloud: {_env_label(detected)}")
    print()

    public_label = "AzurePublicCloud   (commercial — portal.azure.com)"
    gov_label = "AzureUSGovernment  (FedRAMP/government — portal.azure.us)"
    if detected == "government":
        gov_label += "   [detected]"
    elif detected == "public":
        public_label += "   [detected]"

    options = [public_label, gov_label]
    choice = cli_ui.prompt_menu("ENVIRONMENT", options, allow_back=False, allow_main=False)
    return "government" if choice == 2 else "public"


# ---------------------------------------------------------------------------
# Subscription discovery & selection
# ---------------------------------------------------------------------------

def discover_subscriptions() -> list:
    print("\nDiscovering accessible subscriptions...", end=" ", flush=True)
    try:
        subs = utils.list_subscriptions()
    except utils.AzureAccessError as exc:
        print("FAILED.")
        print(f"  {exc}")
        print(f"  Environment in use: {_env_label(exc.environment)}. If that is the wrong cloud, re-run and choose the other;")
        print("  otherwise check your sign-in (`az login`).")
        log.error("Subscription discovery failed: %s", exc)
        sys.exit(1)
    print(f"found {len(subs)}.")
    return subs


def _auto_run_subscriptions(subs: list) -> list:
    requested = utils.get_auto_subscriptions()
    if not requested:
        return subs
    return _entries_for_ids(requested, subs)


def _entries_for_ids(ids: list[str], subs: list) -> list:
    discovered = {sub["id"]: sub for sub in subs}
    return [
        discovered.get(sub_id, {"id": sub_id, "name": sub_id, "state": "Unknown", "tenant_id": ""})
        for sub_id in ids
    ]


def _parse_selection(raw: str, count: int) -> list[int] | None:
    """Parse "1,3,4" into 0-based indexes; None when any entry is out of range."""
    picked: list[int] = []
    for part in raw.replace(" ", "").split(","):
        if not part:
            continue
        try:
            idx = int(part) - 1
        except ValueError:
            return None
        if not 0 <= idx < count:
            return None
        if idx not in picked:
            picked.append(idx)
    return picked or None


def _prompt_single(subs: list) -> list:
    while True:
        raw = cli_ui.prompt_text(f"  Enter subscription number (1–{len(subs)}): ")
        picked = _parse_selection(raw, len(subs))
        if picked and len(picked) == 1:
            return [subs[picked[0]]]
        print(f"  Invalid number. Enter 1–{len(subs)}.")


def _prompt_multiple(subs: list) -> list:
    while True:
        raw = cli_ui.prompt_text(f"  Enter subscription numbers, comma-separated (1–{len(subs)}): ")
        picked = _parse_selection(raw, len(subs))
        if picked:
            return [subs[i] for i in picked]
        print(f"  Invalid selection. Enter comma-separated numbers in 1–{len(subs)}.")


def _prompt_manual() -> list:
    while True:
        sub_id = cli_ui.prompt_text("  Enter subscription ID (GUID): ")
        if utils.is_subscription_id(sub_id):
            return [{"id": sub_id, "name": sub_id, "state": "Unknown", "tenant_id": ""}]
        print("  That is not a subscription ID. Azure subscription IDs are GUIDs")
        print("  (00000000-0000-0000-0000-000000000000).")


def select_subscriptions(subs: list) -> list:
    if utils.is_auto_run():
        return _auto_run_subscriptions(subs)

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
        "Select multiple (comma-separated numbers)",
        "Use all subscriptions",
        "Enter subscription ID manually",
    ]
    choice = cli_ui.prompt_menu("SUBSCRIPTION", options, allow_back=False, allow_main=False)

    if choice == 1:
        return _prompt_single(subs)
    if choice == 2:
        return _prompt_multiple(subs)
    if choice == 3:
        return subs
    if choice == 4:
        return _prompt_manual()
    return []


# ---------------------------------------------------------------------------
# Config write
# ---------------------------------------------------------------------------

def build_and_save_config(environment: str, selected_subs: list, default_id: str = "") -> dict:
    existing = utils.get_config()
    ids = [sub["id"] for sub in selected_subs]
    if default_id and default_id not in ids:
        selected_subs = _entries_for_ids([default_id], selected_subs) + selected_subs
        ids = [sub["id"] for sub in selected_subs]

    config = {
        **existing,
        "environment": environment,
        "subscriptions": selected_subs,
        "default_subscription_id": default_id or (ids[0] if ids else ""),
    }
    utils.save_config(config)
    return config


def _print_summary(config: dict) -> None:
    environment = config["environment"]
    label = (
        f"auto (resolves to {_env_label(utils.detect_environment())})"
        if environment == "auto" else _env_label(environment)
    )
    print("\n" + "=" * 64)
    print("  CONFIGURATION SAVED")
    print("=" * 64)
    print(f"  Environment:          {label}")
    print(f"  Default subscription: {config['default_subscription_id']}")
    print(f"  Subscriptions:        {len(config['subscriptions'])}")
    print()
    print("  Run stratusscan.py to start exporting.")
    print("=" * 64 + "\n")


# ---------------------------------------------------------------------------
# Headless flags
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="configure",
        description="StratusScanCLI-Azure — configure environment and subscriptions",
    )
    parser.add_argument(
        "--environment", choices=ENVIRONMENT_CHOICES,
        help="cloud to write to config.json ('auto' re-detects at run time)",
    )
    parser.add_argument(
        "--subscriptions", metavar="IDS",
        help="comma-separated subscription IDs to save, or 'all' for every accessible one",
    )
    parser.add_argument(
        "--default", dest="default_subscription", metavar="ID",
        help="subscription ID to save as the default target",
    )
    parser.add_argument(
        "--validate", action="store_true",
        help="list the subscriptions the current credential can see, then exit",
    )
    parser.add_argument(
        "--show", action="store_true",
        help="print the current configuration, then exit",
    )
    return parser


def _show_config() -> None:
    config = utils.get_config()
    path = utils.config_path()
    print(f"\nConfiguration: {path}{'' if path.exists() else '  (not written yet — defaults shown)'}")
    print("=" * 64)
    print(f"  Environment:          {config.get('environment', 'auto')}")
    print(f"  Resolved cloud:       {_env_label(utils.detect_environment())}")
    print(f"  Default subscription: {config.get('default_subscription_id') or '(none)'}")
    print(f"  Output directory:     {utils.output_dir()}")
    subs = config.get("subscriptions", [])
    print(f"  Subscriptions:        {len(subs)}")
    for sub in subs:
        print(f"    • {sub.get('name', sub.get('id'))}  ({sub.get('id')})")
    print("=" * 64 + "\n")


def _validate() -> None:
    print(f"\nEnvironment: {_env_label(utils.detect_environment())}")
    subs = discover_subscriptions()
    for sub in subs:
        state = f"  [{sub['state']}]" if sub.get("state") else ""
        print(f"  • {sub['name']}{state}")
        print(f"    {sub['id']}")
    if not subs:
        print("  No subscriptions are visible to this credential.")
    print()


def _invalid_ids(ids: list[str]) -> list[str]:
    return [sub_id for sub_id in ids if not utils.is_subscription_id(sub_id)]


def _run_headless(args: argparse.Namespace) -> None:
    """Write config.json from flags alone — no prompts, for CI and scripted setup."""
    existing = utils.get_config()
    environment = args.environment or existing.get("environment") or "auto"
    if environment != "auto":
        os.environ["AZURE_ENVIRONMENT"] = _env_label(environment)

    raw = (args.subscriptions or "").strip()
    selected = list(existing.get("subscriptions", []))
    if raw.lower() == "all":
        selected = discover_subscriptions()
    elif raw:
        ids = [part.strip() for part in raw.split(",") if part.strip()]
        invalid = _invalid_ids(ids)
        if invalid:
            print(f"ERROR: not subscription IDs (GUIDs expected): {', '.join(invalid)}", file=sys.stderr)
            sys.exit(2)
        try:
            discovered = utils.list_subscriptions()
        except (utils.AzureAccessError, ImportError) as exc:
            log.info("Naming subscriptions without discovery: %s", exc)
            discovered = []
        selected = _entries_for_ids(ids, discovered)

    default_id = (args.default_subscription or "").strip()
    if default_id and not utils.is_subscription_id(default_id):
        print(f"ERROR: --default is not a subscription ID (GUID expected): {default_id}", file=sys.stderr)
        sys.exit(2)

    config = build_and_save_config(environment, selected, default_id)
    log.info("Config saved headlessly — environment=%s, subscriptions=%d", environment, len(selected))
    _print_summary(config)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(sys.argv[1:] if argv is None else argv)

    bootstrap.ensure_dependencies()
    utils.setup_logging("configure", log_to_file=True)
    utils.log_script_start("configure.py", "StratusScan Configuration Wizard")

    print("\n" + "=" * 64)
    print("  StratusScanCLI-Azure — Configuration Wizard")
    print(f"  Version: {utils.get_version()}")
    print("=" * 64)

    try:
        utils.detect_environment()
    except ValueError as exc:
        print(f"ERROR: {exc}")
        sys.exit(2)

    if args.show:
        _show_config()
        return
    if args.validate:
        _validate()
        return
    if args.environment or args.subscriptions or args.default_subscription:
        _run_headless(args)
        return

    print("  This wizard configures your Azure environment and subscription.")
    print()

    try:
        environment = select_environment()
        log.info("Environment selected: %s", environment)

        # Apply the selected cloud before subscription discovery so credentials use
        # the correct authority and resource manager endpoint.
        os.environ["AZURE_ENVIRONMENT"] = _env_label(environment)

        subs = discover_subscriptions()
        selected = select_subscriptions(subs)
    except cli_ui.QuitRequested:
        print("Goodbye.")
        sys.exit(0)

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
