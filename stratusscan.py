#!/usr/bin/env python3
"""
StratusScanCLI-Azure — Main Menu
Version: v0.1.0

Launches Azure resource exporter scripts as subprocesses.
This script never calls Azure APIs directly — all API work happens in the exporter scripts.

Usage:
    python stratusscan.py
    STRATUSSCAN_AUTO_RUN=1 STRATUSSCAN_SUBSCRIPTIONS=sub-id python stratusscan.py
"""

import os
import subprocess
import sys
from pathlib import Path
from typing import Optional

# Ensure local modules are importable from the project root.
sys.path.insert(0, str(Path(__file__).parent))

import bootstrap

bootstrap.ensure_dependencies()

try:
    import utils
except ImportError:
    print("ERROR: Could not import utils.py. Make sure it is in the same directory.")
    sys.exit(1)

utils.setup_logging("main-menu", log_to_file=True)
utils.log_script_start("stratusscan.py", "StratusScan Main Menu")
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
    ("Key Vault Objects (Keys/Secrets/Certs)", "key_vault_objects_export.py"),
    ("RBAC Role Assignments",          "role_assignments_export.py"),
]

TIER2_EXPORTERS = [
    ("AKS Clusters",                   "aks_clusters_export.py"),
    ("Container Registries (ACR)",     "container_registry_export.py"),
    ("Container Apps",                 "container_apps_export.py"),
    ("Container Instances (ACI)",      "container_instances_export.py"),
    ("App Service / Web Apps",         "app_service_export.py"),
    ("Function Apps",                  "function_apps_export.py"),
    ("Azure SQL Databases",            "azure_sql_export.py"),
    ("SQL Managed Instances",          "sql_managed_instance_export.py"),
    ("Cosmos DB Accounts",             "cosmos_db_export.py"),
    ("PostgreSQL Flexible Servers",    "postgresql_flexible_export.py"),
    ("MySQL Flexible Servers",         "mysql_flexible_export.py"),
    ("Redis Caches",                   "redis_cache_export.py"),
    ("Load Balancers",                 "load_balancers_export.py"),
    ("DNS Zones (public + private)",   "dns_zones_export.py"),
    ("Front Door & CDN Profiles",      "front_door_export.py"),
    ("Traffic Manager Profiles",       "traffic_manager_export.py"),
    ("Event Hubs Namespaces",          "event_hubs_export.py"),
    ("Service Bus Namespaces",         "service_bus_export.py"),
    ("API Management Services",        "api_management_export.py"),
    ("Logic Apps (Workflows)",         "logic_apps_export.py"),
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
    ("Automation Accounts",            "automation_accounts_export.py"),
    ("Batch Accounts",                 "batch_accounts_export.py"),
    ("Recovery Services Vaults",       "recovery_services_vaults_export.py"),
]

GOVERNANCE_EXPORTERS = [
    ("Azure Policy Assignments",       "policy_assignments_export.py"),
    ("Management Groups",              "management_groups_export.py"),
    ("Defender Secure Scores & Plans", "defender_scores_export.py"),
    ("Defender Assessments",           "defender_assessments_export.py"),
    ("Advisor Recommendations",        "advisor_export.py"),
    ("Resource Locks",                 "resource_locks_export.py"),
    ("Resource Tags Inventory",        "resource_tags_export.py"),
    ("Custom Policy Definitions",      "policy_definitions_export.py"),
    ("Policy Compliance State",        "policy_compliance_export.py"),
    ("Managed Identities",             "managed_identities_export.py"),
    ("Cost Management (Month-to-Date)", "cost_management_export.py"),
]

MONITORING_EXPORTERS = [
    ("Metric & Activity Log Alerts",   "metric_alerts_export.py"),
    ("Action Groups",                  "action_groups_export.py"),
    ("Log Analytics Workspaces",       "log_analytics_export.py"),
    ("Diagnostic Settings (audit)",    "diagnostic_settings_export.py"),
    ("Application Insights",           "application_insights_export.py"),
]


# ---------------------------------------------------------------------------
# Subscription resolution
# ---------------------------------------------------------------------------

def _active_subscriptions() -> list:
    """
    Return the list of (id, name) subscriptions to scan in interactive mode.

    Every subscription saved by configure.py is scanned ("Use all subscriptions"
    works as expected); falls back to the default, then to an empty list when
    nothing is configured.
    """
    cfg = utils.get_config()
    pairs = [
        (s["id"], s.get("name", s["id"]))
        for s in cfg.get("subscriptions", [])
        if s.get("id")
    ]
    if pairs:
        return pairs
    sub_id = cfg.get("default_subscription_id", "")
    if sub_id:
        return [(sub_id, utils.get_subscription_name(sub_id))]
    return []


def _autodiscover_subscriptions() -> list:
    """
    Discover all accessible (enabled) subscriptions when nothing is configured,
    so stratusscan.py runs with zero setup. configure.py is then only needed to
    persist a choice or narrow to specific subscriptions.
    """
    print("\nNo configuration found — auto-detecting environment and discovering subscriptions...")
    try:
        discovered = utils.list_subscriptions()
    except Exception as exc:
        print(f"  Subscription discovery failed: {exc}")
        return []
    pairs = [
        (s["id"], s.get("name", s["id"]))
        for s in discovered
        if s.get("id") and (not s.get("state") or "enabled" in str(s["state"]).lower())
    ]
    if pairs:
        env_label = (
            "AzureUSGovernment" if utils.detect_environment() == "government" else "AzurePublicCloud"
        )
        print(f"  Environment: {env_label}")
        print(f"  Found {len(pairs)} accessible subscription(s). Scanning all — run Configure to narrow.")
    return pairs


# ---------------------------------------------------------------------------
# Subprocess launcher
# ---------------------------------------------------------------------------

def _run_exporter(script_rel_path: str, sub_id: str, sub_name: str) -> int:
    script_path = SCRIPTS_DIR / script_rel_path
    if not script_path.exists():
        print(f"ERROR: Script not found: {script_path}")
        return 1

    env = os.environ.copy()
    env["STRATUSSCAN_SUBSCRIPTION_ID"] = sub_id
    env["STRATUSSCAN_SUBSCRIPTION_NAME"] = sub_name

    result = subprocess.run(
        [sys.executable, str(script_path)],
        env=env,
    )
    return result.returncode


# ---------------------------------------------------------------------------
# Menu helpers
# ---------------------------------------------------------------------------

def _print_banner() -> None:
    env = utils.detect_environment()
    env_label = "AzureUSGovernment" if env == "government" else "AzurePublicCloud"
    version = utils.get_version()

    print("\n" + "=" * 64)
    print("  StratusScanCLI-Azure — Azure Resource Exporter")
    print(f"  Version: {version}  |  Environment: {env_label}")
    print("=" * 64)


def _subs_label(subs: list) -> str:
    if len(subs) == 1:
        return subs[0][1]
    return f"{len(subs)} subscriptions"


def _primary_subscription(subs: list) -> list:
    """
    Return a single-subscription list for the default Run-All target: the
    configured default subscription if it is among the active ones, otherwise
    the first.
    """
    default_id = utils.get_config().get("default_subscription_id", "")
    if default_id:
        for pair in subs:
            if pair[0] == default_id:
                return [pair]
    return subs[:1]


def _select_run_all_subs(subs: list):
    """
    Run-All scans one subscription by default to stay Cloud Shell-friendly
    (running every exporter across many subscriptions can exceed the session
    timeout). With more than one active subscription, require an explicit
    opt-in to scan them all.

    Returns the chosen (id, name) list, or None if the user backs out.
    """
    if len(subs) <= 1:
        return subs
    primary = _primary_subscription(subs)
    options = [
        f"{primary[0][1]} only  (current subscription — recommended)",
        f"All {len(subs)} subscriptions  (slower — may time out in Cloud Shell)",
    ]
    choice = utils.prompt_menu(
        "RUN ALL — SELECT SCOPE",
        options,
        allow_back=True,
        allow_exit=False,
    )
    if choice == "back":
        return None
    if choice == 2:
        return subs
    return primary


def _run_exporter_across(path: str, label: str, subs: list) -> None:
    for sub_id, sub_name in subs:
        if len(subs) > 1:
            print(f"  [{sub_name}]", end=" ", flush=True)
        _run_exporter(path, sub_id, sub_name)


def _run_all_exporters(
    exporters: list,
    subs: list,
    package_outputs: bool = False,
    package_label: Optional[str] = None,
) -> None:
    print(f"\nRunning {len(exporters)} exporter(s) across {_subs_label(subs)}...\n")
    failed = []
    for sub_id, sub_name in subs:
        if len(subs) > 1:
            print(f"=== Subscription: {sub_name} ({sub_id}) ===")
        for label, path in exporters:
            print(f"  → {label}...", end=" ", flush=True)
            rc = _run_exporter(path, sub_id, sub_name)
            if rc == 0:
                print("done")
            else:
                print(f"FAILED (exit {rc})")
                failed.append(f"{label} [{sub_name}]" if len(subs) > 1 else label)
        if len(subs) > 1:
            print()
    print()
    total = len(exporters) * len(subs)
    if failed:
        print(f"Completed with {len(failed)}/{total} failure(s): {', '.join(failed)}")
    else:
        print(f"All {total} exporter run(s) completed successfully.")

    if package_outputs:
        _package_outputs(package_label)


def _package_outputs(label: Optional[str] = None) -> None:
    zip_path = utils.archive_outputs(label)
    if not zip_path:
        print("\nNo exports found in output/ to package.")
        return
    print(f"\nPackaged exports → {zip_path}")
    print(f"  In Cloud Shell, download it with: download {zip_path}")


# ---------------------------------------------------------------------------
# Menus
# ---------------------------------------------------------------------------

def _run_tier_menu(title: str, exporters: list, subs: list) -> None:
    while True:
        options = [label for label, _ in exporters] + [f"Run All {title} Exporters"]
        choice = utils.prompt_menu(
            f"{title.upper()} EXPORTERS  ({_subs_label(subs)})",
            options,
            allow_back=True,
            allow_exit=True,
        )
        if choice == "back":
            return
        if choice == "exit":
            sys.exit(0)
        if choice == len(options):
            target = _select_run_all_subs(subs)
            if target:
                _run_all_exporters(
                    exporters,
                    target,
                    package_outputs=True,
                    package_label=title.replace(" ", "").lower(),
                )
        else:
            label, path = exporters[choice - 1]
            print(f"\nRunning: {label}")
            _run_exporter_across(path, label, subs)


def menu_tier1(subs: list) -> None:
    _run_tier_menu("Tier 1", TIER1_EXPORTERS, subs)


def menu_tier2(subs: list) -> None:
    _run_tier_menu("Tier 2", TIER2_EXPORTERS, subs)


def menu_governance(subs: list) -> None:
    _run_tier_menu("Governance", GOVERNANCE_EXPORTERS, subs)


def menu_monitoring(subs: list) -> None:
    _run_tier_menu("Monitoring", MONITORING_EXPORTERS, subs)


def menu_main(subs: list) -> None:
    _print_banner()
    if len(subs) > 1:
        print(f"  {len(subs)} subscriptions available:")
        for _, sname in subs:
            print(f"    • {sname}")
        print("  (Run All scans one by default — choose scope when prompted.)")
        print()
    while True:
        options = [
            "Tier 1 Exporters   (Core infrastructure: VMs, VNets, Storage, Key Vault, RBAC…)",
            "Tier 2 Exporters   (Workloads: AKS, App Service, SQL, Cosmos DB, Gateways…)",
            "Governance          (Policy, Management Groups, Defender, Advisor…)",
            "Monitoring          (Alerts, Action Groups, Log Analytics…)",
            "Run All Exporters   (Tier 1 + Tier 2 + Governance + Monitoring)",
            "Package Outputs     (zip all exports for Cloud Shell download)",
            "Configure           (subscription selection, environment settings)",
        ]
        choice = utils.prompt_menu(
            f"STRATUSSCAN MAIN MENU  ({_subs_label(subs)})",
            options,
            allow_back=False,
            allow_exit=True,
        )
        if choice == "exit":
            print("Goodbye.")
            sys.exit(0)
        if choice == 1:
            menu_tier1(subs)
        elif choice == 2:
            menu_tier2(subs)
        elif choice == 3:
            menu_governance(subs)
        elif choice == 4:
            menu_monitoring(subs)
        elif choice == 5:
            target = _select_run_all_subs(subs)
            if target:
                _run_all_exporters(
                    TIER1_EXPORTERS + TIER2_EXPORTERS + GOVERNANCE_EXPORTERS + MONITORING_EXPORTERS,
                    target,
                    package_outputs=True,
                    package_label="all",
                )
        elif choice == 6:
            _package_outputs()
        elif choice == 7:
            subprocess.run([sys.executable, str(Path(__file__).parent / "configure.py")])
            # Reload config after configure, then re-resolve active subscriptions
            import importlib
            importlib.reload(utils)
            subs = _active_subscriptions() or subs


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    if utils.is_auto_run():
        auto_subs = utils.get_auto_subscriptions()
        if auto_subs:
            subs = [(sid, utils.get_subscription_name(sid)) for sid in auto_subs]
        else:
            subs = _active_subscriptions() or _autodiscover_subscriptions()
        if not subs:
            print("\nNo subscriptions to scan (none set, configured, or discoverable).")
            sys.exit(1)
        print(f"\nAuto-run: scanning {_subs_label(subs)}")
        _run_all_exporters(
            TIER1_EXPORTERS + TIER2_EXPORTERS + GOVERNANCE_EXPORTERS + MONITORING_EXPORTERS,
            subs,
            package_outputs=True,
            package_label="all",
        )
        return

    subs = _active_subscriptions() or _autodiscover_subscriptions()
    if not subs:
        print("\nNo accessible subscriptions found.")
        print("  Check your Azure sign-in (e.g. `az login`), then try again.")
        sys.exit(1)
    menu_main(subs)


if __name__ == "__main__":
    main()
