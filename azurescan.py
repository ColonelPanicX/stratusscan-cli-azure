#!/usr/bin/env python3
"""
StratusScanCLI-Azure — Main Menu
Version: v0.1.0

Launches Azure resource exporter scripts as subprocesses.
This script never calls Azure APIs directly — all API work happens in the exporter scripts.

Usage:
    python azurescan.py
    AZURESCAN_AUTO_RUN=1 AZURESCAN_SUBSCRIPTIONS=sub-id python azurescan.py
"""

import os
import subprocess
import sys
from pathlib import Path

# Ensure utils is importable from the project root
sys.path.insert(0, str(Path(__file__).parent))

try:
    import utils
except ImportError:
    print("ERROR: Could not import utils.py. Make sure it is in the same directory.")
    sys.exit(1)

utils.setup_logging("main-menu", log_to_file=True)
utils.log_script_start("azurescan.py", "AzureScan Main Menu")
utils.log_system_info()

SCRIPTS_DIR = Path(__file__).parent / "scripts"

# ---------------------------------------------------------------------------
# Exporter registry
# Each entry: (display_label, relative_path_from_scripts_dir)
# ---------------------------------------------------------------------------

TIER1_EXPORTERS = [
    ("Subscriptions",                  "subscriptions_export.py"),
    ("Resource Groups",                "resource_groups_export.py"),
    ("Virtual Machines",               "virtual_machines_export.py"),
    ("VM Scale Sets",                  "vmss_export.py"),
    ("Managed Disks",                  "managed_disks_export.py"),
    ("Virtual Networks",               "virtual_networks_export.py"),
    ("Subnets",                        "subnets_export.py"),
    ("Network Security Groups",        "network_security_groups_export.py"),
    ("Public IP Addresses",            "public_ips_export.py"),
    ("Storage Accounts",               "storage_accounts_export.py"),
    ("Key Vaults",                     "key_vault_export.py"),
    ("RBAC Role Assignments",          "role_assignments_export.py"),
]

TIER2_EXPORTERS = [
    ("AKS Clusters",                   "aks_clusters_export.py"),
    ("App Service / Web Apps",         "app_service_export.py"),
    ("Function Apps",                  "function_apps_export.py"),
    ("Azure SQL Databases",            "azure_sql_export.py"),
    ("Cosmos DB Accounts",             "cosmos_db_export.py"),
    ("Load Balancers",                 "load_balancers_export.py"),
    ("Application Gateways",           "application_gateway_export.py"),
    ("Azure Firewalls",                "azure_firewall_export.py"),
    ("Firewall Policy Rules",          "firewall_policy_rules_export.py"),
    ("Route Tables",                   "route_tables_export.py"),
    ("VNet Peerings",                  "vnet_peerings_export.py"),
    ("Snapshots",                      "snapshots_export.py"),
    ("Availability Sets",              "availability_sets_export.py"),
    ("Private Endpoints",              "private_endpoints_export.py"),
    ("NAT Gateways",                   "nat_gateways_export.py"),
    ("Bastion Hosts",                  "bastion_hosts_export.py"),
    ("VPN Gateways",                   "vpn_gateways_export.py"),
    ("ExpressRoute Circuits",          "expressroute_export.py"),
    ("Virtual WAN & Hubs",             "virtual_wan_export.py"),
    ("DDoS Protection Plans",          "ddos_protection_export.py"),
    ("Network Watchers",               "network_watchers_export.py"),
    ("Service Endpoints",              "service_endpoints_export.py"),
    ("Blob Containers",                "blob_containers_export.py"),
    ("File Shares",                    "file_shares_export.py"),
]

GOVERNANCE_EXPORTERS = [
    ("Azure Policy Assignments",       "policy_assignments_export.py"),
    ("Management Groups",              "management_groups_export.py"),
    ("Defender Secure Scores & Plans", "defender_scores_export.py"),
    ("Defender Assessments",           "defender_assessments_export.py"),
    ("Advisor Recommendations",        "advisor_export.py"),
]

MONITORING_EXPORTERS = [
    ("Metric & Activity Log Alerts",   "metric_alerts_export.py"),
    ("Action Groups",                  "action_groups_export.py"),
    ("Log Analytics Workspaces",       "log_analytics_export.py"),
]


# ---------------------------------------------------------------------------
# Subscription resolution
# ---------------------------------------------------------------------------

def _resolve_subscription() -> tuple[str, str]:
    """
    Return (subscription_id, subscription_name) from config or env var.
    In auto-run mode, use the first subscription from AZURESCAN_SUBSCRIPTIONS.
    """
    if utils.is_auto_run():
        auto_subs = utils.get_auto_subscriptions()
        if auto_subs:
            sub_id = auto_subs[0]
            return sub_id, utils.get_subscription_name(sub_id)

    cfg = utils.get_config()
    sub_id = cfg.get("default_subscription_id", "")
    if not sub_id:
        print("\nNo subscription configured. Run configure.py first.")
        print("  python configure.py")
        sys.exit(1)
    return sub_id, utils.get_subscription_name(sub_id)


# ---------------------------------------------------------------------------
# Subprocess launcher
# ---------------------------------------------------------------------------

def _run_exporter(script_rel_path: str, sub_id: str, sub_name: str) -> int:
    script_path = SCRIPTS_DIR / script_rel_path
    if not script_path.exists():
        print(f"ERROR: Script not found: {script_path}")
        return 1

    env = os.environ.copy()
    env["AZURESCAN_SUBSCRIPTION_ID"] = sub_id
    env["AZURESCAN_SUBSCRIPTION_NAME"] = sub_name

    result = subprocess.run(
        [sys.executable, str(script_path)],
        env=env,
    )
    return result.returncode


# ---------------------------------------------------------------------------
# Menu helpers
# ---------------------------------------------------------------------------

def _print_banner() -> None:
    cfg = utils.get_config()
    env = utils.detect_environment()
    env_label = "AzureUSGovernment" if env == "government" else "AzurePublicCloud"
    version = utils.get_version()

    print("\n" + "=" * 64)
    print("  StratusScanCLI-Azure — Azure Resource Exporter")
    print(f"  Version: {version}  |  Environment: {env_label}")
    print("=" * 64)


def _run_all_exporters(exporters: list, sub_id: str, sub_name: str) -> None:
    print(f"\nRunning {len(exporters)} exporter(s)...\n")
    failed = []
    for label, path in exporters:
        print(f"  → {label}...", end=" ", flush=True)
        rc = _run_exporter(path, sub_id, sub_name)
        if rc == 0:
            print("done")
        else:
            print(f"FAILED (exit {rc})")
            failed.append(label)
    print()
    if failed:
        print(f"Completed with {len(failed)} failure(s): {', '.join(failed)}")
    else:
        print(f"All {len(exporters)} exporter(s) completed successfully.")


# ---------------------------------------------------------------------------
# Menus
# ---------------------------------------------------------------------------

def menu_tier1(sub_id: str, sub_name: str) -> None:
    while True:
        options = [label for label, _ in TIER1_EXPORTERS] + ["Run All Tier 1 Exporters"]
        choice = utils.prompt_menu(
            f"TIER 1 EXPORTERS  ({sub_name})",
            options,
            allow_back=True,
            allow_exit=True,
        )
        if choice == "back":
            return
        if choice == "exit":
            sys.exit(0)
        if choice == len(options):
            _run_all_exporters(TIER1_EXPORTERS, sub_id, sub_name)
        else:
            label, path = TIER1_EXPORTERS[choice - 1]
            print(f"\nRunning: {label}")
            _run_exporter(path, sub_id, sub_name)


def menu_tier2(sub_id: str, sub_name: str) -> None:
    while True:
        options = [label for label, _ in TIER2_EXPORTERS] + ["Run All Tier 2 Exporters"]
        choice = utils.prompt_menu(
            f"TIER 2 EXPORTERS  ({sub_name})",
            options,
            allow_back=True,
            allow_exit=True,
        )
        if choice == "back":
            return
        if choice == "exit":
            sys.exit(0)
        if choice == len(options):
            _run_all_exporters(TIER2_EXPORTERS, sub_id, sub_name)
        else:
            label, path = TIER2_EXPORTERS[choice - 1]
            print(f"\nRunning: {label}")
            _run_exporter(path, sub_id, sub_name)


def menu_governance(sub_id: str, sub_name: str) -> None:
    while True:
        options = [label for label, _ in GOVERNANCE_EXPORTERS] + ["Run All Governance Exporters"]
        choice = utils.prompt_menu(
            f"GOVERNANCE EXPORTERS  ({sub_name})",
            options,
            allow_back=True,
            allow_exit=True,
        )
        if choice == "back":
            return
        if choice == "exit":
            sys.exit(0)
        if choice == len(options):
            _run_all_exporters(GOVERNANCE_EXPORTERS, sub_id, sub_name)
        else:
            label, path = GOVERNANCE_EXPORTERS[choice - 1]
            print(f"\nRunning: {label}")
            _run_exporter(path, sub_id, sub_name)


def menu_monitoring(sub_id: str, sub_name: str) -> None:
    while True:
        options = [label for label, _ in MONITORING_EXPORTERS] + ["Run All Monitoring Exporters"]
        choice = utils.prompt_menu(
            f"MONITORING EXPORTERS  ({sub_name})",
            options,
            allow_back=True,
            allow_exit=True,
        )
        if choice == "back":
            return
        if choice == "exit":
            sys.exit(0)
        if choice == len(options):
            _run_all_exporters(MONITORING_EXPORTERS, sub_id, sub_name)
        else:
            label, path = MONITORING_EXPORTERS[choice - 1]
            print(f"\nRunning: {label}")
            _run_exporter(path, sub_id, sub_name)


def menu_main(sub_id: str, sub_name: str) -> None:
    _print_banner()
    while True:
        options = [
            "Tier 1 Exporters   (Core infrastructure: VMs, VNets, Storage, Key Vault, RBAC…)",
            "Tier 2 Exporters   (Workloads: AKS, App Service, SQL, Cosmos DB, Gateways…)",
            "Governance          (Policy, Management Groups, Defender, Advisor…)",
            "Monitoring          (Alerts, Action Groups, Log Analytics…)",
            "Run All Exporters   (Tier 1 + Tier 2 + Governance + Monitoring)",
            "Configure           (subscription selection, environment settings)",
        ]
        choice = utils.prompt_menu(
            "AZURESCAN MAIN MENU",
            options,
            allow_back=False,
            allow_exit=True,
        )
        if choice == "exit":
            print("Goodbye.")
            sys.exit(0)
        if choice == 1:
            menu_tier1(sub_id, sub_name)
        elif choice == 2:
            menu_tier2(sub_id, sub_name)
        elif choice == 3:
            menu_governance(sub_id, sub_name)
        elif choice == 4:
            menu_monitoring(sub_id, sub_name)
        elif choice == 5:
            _run_all_exporters(TIER1_EXPORTERS + TIER2_EXPORTERS + GOVERNANCE_EXPORTERS + MONITORING_EXPORTERS, sub_id, sub_name)
        elif choice == 6:
            subprocess.run([sys.executable, str(Path(__file__).parent / "configure.py")])
            # Reload config after configure
            import importlib
            importlib.reload(utils)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    sub_id, sub_name = _resolve_subscription()

    if utils.is_auto_run():
        auto_subs = utils.get_auto_subscriptions()
        all_subs = auto_subs if auto_subs else [sub_id]
        for sid in all_subs:
            sname = utils.get_subscription_name(sid)
            print(f"\nAuto-run: scanning subscription {sname} ({sid})")
            _run_all_exporters(TIER1_EXPORTERS + TIER2_EXPORTERS + GOVERNANCE_EXPORTERS + MONITORING_EXPORTERS, sid, sname)
        return

    menu_main(sub_id, sub_name)


if __name__ == "__main__":
    main()
