#!/usr/bin/env python3
"""
StratusScanCLI-Azure — Main Menu
Version: v0.1.0

Launches Azure resource exporter scripts as subprocesses.
This script never calls Azure APIs directly — all API work happens in the exporter scripts.

Usage:
    python stratusscan.py                              # interactive menu
    python stratusscan.py --list                       # every tier and exporter name
    python stratusscan.py --dry-run                    # validate, report, run nothing
    python stratusscan.py --run-all --subscriptions all
    python stratusscan.py --tier governance --exporter storage_accounts
    STRATUSSCAN_AUTO_RUN=1 STRATUSSCAN_SUBSCRIPTIONS=sub-id python stratusscan.py
"""

import argparse
import datetime
import logging
import os
import re
import subprocess
import sys
import time
from pathlib import Path

# Ensure local modules are importable from the project root.
sys.path.insert(0, str(Path(__file__).parent))

import bootstrap

try:
    import cli_ui
    import utils
except ImportError:
    print("ERROR: Could not import utils.py. Make sure it is in the same directory.")
    sys.exit(1)

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

TIERS: dict[str, tuple[str, list]] = {
    "tier1": ("Tier 1", TIER1_EXPORTERS),
    "tier2": ("Tier 2", TIER2_EXPORTERS),
    "governance": ("Governance", GOVERNANCE_EXPORTERS),
    "monitoring": ("Monitoring", MONITORING_EXPORTERS),
}

ALL_EXPORTERS = (
    TIER1_EXPORTERS + TIER2_EXPORTERS + GOVERNANCE_EXPORTERS + MONITORING_EXPORTERS
)

# These list tenant-scoped objects, not subscription-scoped ones: the same rows
# come back whichever subscription is targeted, and the second run overwrites the
# first workbook. A multi-subscription Run All therefore runs them once.
TENANT_SCOPED_EXPORTERS = frozenset({
    "subscriptions_export.py",
    "management_groups_export.py",
})

# Tier 2 is 41 exporters; the submenu groups them so the list can be scanned.
# Numbering stays continuous — the headings are labels, not menu entries.
TIER2_CATEGORIES: list[tuple[str, list[str]]] = [
    ("Compute & Containers", [
        "aks_clusters_export.py",
        "container_registry_export.py",
        "container_apps_export.py",
        "container_instances_export.py",
        "app_service_export.py",
        "function_apps_export.py",
        "availability_sets_export.py",
        "snapshots_export.py",
    ]),
    ("Databases", [
        "azure_sql_export.py",
        "sql_managed_instance_export.py",
        "cosmos_db_export.py",
        "postgresql_flexible_export.py",
        "mysql_flexible_export.py",
        "redis_cache_export.py",
    ]),
    ("Networking", [
        "load_balancers_export.py",
        "application_gateway_export.py",
        "azure_firewall_export.py",
        "firewall_policy_rules_export.py",
        "route_tables_export.py",
        "vnet_peerings_export.py",
        "private_endpoints_export.py",
        "nat_gateways_export.py",
        "bastion_hosts_export.py",
        "vpn_gateways_export.py",
        "expressroute_export.py",
        "virtual_wan_export.py",
        "ddos_protection_export.py",
        "network_watchers_export.py",
        "service_endpoints_export.py",
        "dns_zones_export.py",
        "front_door_export.py",
        "traffic_manager_export.py",
    ]),
    ("Integration & Messaging", [
        "event_hubs_export.py",
        "service_bus_export.py",
        "api_management_export.py",
        "logic_apps_export.py",
    ]),
    ("Storage", [
        "blob_containers_export.py",
        "file_shares_export.py",
    ]),
    ("Ops", [
        "automation_accounts_export.py",
        "batch_accounts_export.py",
        "recovery_services_vaults_export.py",
    ]),
]


def grouped_exporters(
    exporters: list, categories: list[tuple[str, list[str]]]
) -> tuple[list, dict[int, str]]:
    """
    Reorder exporters into the given categories and return (ordered, headings),
    where headings maps a 1-based position to the heading printed above it.

    Anything a category does not claim keeps registry order under "Other", so a
    new exporter shows up in the menu even before it is categorized.
    """
    by_path = {path: (label, path) for label, path in exporters}
    ordered: list = []
    headings: dict[int, str] = {}
    for name, paths in categories:
        claimed = [by_path.pop(path) for path in paths if path in by_path]
        if claimed:
            headings[len(ordered) + 1] = name
            ordered.extend(claimed)
    leftover = [entry for entry in exporters if entry[1] in by_path]
    if leftover:
        headings[len(ordered) + 1] = "Other"
        ordered.extend(leftover)
    return ordered, headings


# ---------------------------------------------------------------------------
# Exporter name resolution (--exporter / --list)
# ---------------------------------------------------------------------------

class UnknownExporterError(ValueError):
    """One or more --exporter names matched no registered exporter."""

    def __init__(self, names: list[str]) -> None:
        super().__init__(f"Unknown exporter(s): {', '.join(names)}")
        self.names = names


def exporter_name(script_rel_path: str) -> str:
    """The name --exporter takes: the script stem without the _export suffix."""
    stem = Path(script_rel_path).stem
    return stem[: -len("_export")] if stem.endswith("_export") else stem


def _normalize(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", name.strip().lower()).strip("_")


def _exporter_index() -> dict[str, tuple[str, str]]:
    """Both addressing forms: the script name, and the menu label, case-insensitive."""
    index = {_normalize(exporter_name(path)): (label, path) for label, path in ALL_EXPORTERS}
    for label, path in ALL_EXPORTERS:
        index.setdefault(_normalize(label), (label, path))
    return index


def exporter_names() -> list[str]:
    return [exporter_name(path) for _, path in ALL_EXPORTERS]


def resolve_exporters(names: list[str]) -> list:
    """Return the (label, path) entries for the given names, in the order given."""
    index = _exporter_index()
    chosen: list = []
    unknown: list[str] = []
    for name in names:
        entry = index.get(_normalize(name))
        if entry is None:
            unknown.append(name)
        elif entry not in chosen:
            chosen.append(entry)
    if unknown:
        raise UnknownExporterError(unknown)
    return chosen


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
    except utils.AzureAccessError as exc:
        print(f"  Subscription discovery failed — {exc}")
        print(f"  {exc.hint}")
        sys.exit(1)
    except ImportError as exc:
        print(f"  Subscription discovery failed — {exc}")
        sys.exit(1)
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

STATUS_OK = "OK"
STATUS_EMPTY = "EMPTY"
STATUS_PARTIAL = "PARTIAL"
STATUS_CONFIG = "CONFIG"
STATUS_FAILED = "FAILED"
STATUS_TIMEOUT = "TIMEOUT"
STATUS_SKIPPED = "SKIPPED"

STATUS_BY_EXIT_CODE = {0: STATUS_OK, 3: STATUS_EMPTY, 4: STATUS_PARTIAL, 2: STATUS_CONFIG}
FAILURE_STATUSES = (STATUS_FAILED, STATUS_TIMEOUT, STATUS_PARTIAL, STATUS_CONFIG)

DEFAULT_EXPORTER_TIMEOUT_S = 1800


def new_run_id() -> str:
    return datetime.datetime.now().strftime("%m.%d.%Y-%H%M%S")


def exporter_timeout() -> int:
    return int(os.environ.get("STRATUSSCAN_EXPORTER_TIMEOUT", str(DEFAULT_EXPORTER_TIMEOUT_S)))


def status_for_exit_code(rc: int) -> str:
    return STATUS_BY_EXIT_CODE.get(rc, STATUS_FAILED)


def _run_exporter(script_rel_path: str, sub_id: str, sub_name: str, run_id: str) -> tuple:
    """Run one exporter subprocess; return (status, exit_code, duration_s)."""
    script_path = SCRIPTS_DIR / script_rel_path
    if not script_path.exists():
        print(f"ERROR: Script not found: {script_path}")
        return STATUS_FAILED, 1, 0.0

    env = os.environ.copy()
    env["STRATUSSCAN_SUBSCRIPTION_ID"] = sub_id
    env["STRATUSSCAN_SUBSCRIPTION_NAME"] = sub_name
    env["STRATUSSCAN_RUN_ID"] = run_id

    started = time.monotonic()
    try:
        result = subprocess.run(
            [sys.executable, str(script_path)],
            env=env,
            timeout=exporter_timeout(),
        )
    except subprocess.TimeoutExpired:
        # subprocess.run kills the child before re-raising TimeoutExpired.
        duration = round(time.monotonic() - started, 1)
        utils.record_run_result(
            run_id=run_id,
            script=_script_name(script_rel_path),
            subscription_id=sub_id,
            subscription_name=sub_name,
            status=STATUS_TIMEOUT,
            exit_code=None,
            rows=None,
            file=None,
            errors=0,
            detail=f"killed after {exporter_timeout()}s",
            duration_s=duration,
        )
        return STATUS_TIMEOUT, None, duration
    duration = round(time.monotonic() - started, 1)
    return status_for_exit_code(result.returncode), result.returncode, duration


def _script_name(script_rel_path: str) -> str:
    return exporter_name(script_rel_path).replace("_", "-")


def _manifest_record(run_id: str, script_rel_path: str, sub_id: str) -> dict:
    """The exporter's own manifest line for this run, if it wrote one."""
    name = _script_name(script_rel_path)
    for record in reversed(utils.read_run_results(run_id)):
        if record.get("script") == name and record.get("subscription_id") == sub_id:
            return record
    return {}


def _outcome_line(status: str, rc: int | None, duration: float, record: dict) -> str:
    if status == STATUS_OK:
        if record.get("status") == STATUS_SKIPPED:
            return f"{STATUS_SKIPPED} ({duration}s)"
        rows = record.get("rows")
        rows_part = f"{rows} rows, " if rows is not None else ""
        return f"OK ({rows_part}{duration}s)"
    if status == STATUS_EMPTY:
        return f"EMPTY ({duration}s)"
    if status == STATUS_PARTIAL:
        rows = record.get("rows")
        rows_part = f"{rows} rows, " if rows is not None else ""
        return f"PARTIAL ({rows_part}{record.get('errors', '?')} errors, {duration}s)"
    if status == STATUS_TIMEOUT:
        return f"TIMEOUT (killed after {exporter_timeout()}s)"
    if status == STATUS_CONFIG:
        return f"CONFIG (exit {rc})"
    return f"FAILED (exit {rc})"


def _launch(label: str, path: str, sub_id: str, sub_name: str, run_id: str, outcomes: list) -> str:
    """Run one exporter, print its outcome line, append to outcomes; return the status."""
    print(f"  → {label}...", end=" ", flush=True)
    status, rc, duration = _run_exporter(path, sub_id, sub_name, run_id)
    record = _manifest_record(run_id, path, sub_id)
    if status == STATUS_OK and record.get("status") == STATUS_SKIPPED:
        status = STATUS_SKIPPED
    print(_outcome_line(status, rc, duration, record))
    outcomes.append({
        "Exporter": label,
        "Subscription": sub_name,
        "Status": status,
        "Rows": record.get("rows", ""),
        "Errors": record.get("errors", 0) if status == STATUS_PARTIAL else "",
        "Duration (s)": duration,
        "File": record.get("file") or "",
        "Exit Code": "" if rc is None else rc,
    })
    return status


# ---------------------------------------------------------------------------
# Menu helpers
# ---------------------------------------------------------------------------

def _environment_label() -> str:
    return "AzureUSGovernment" if utils.detect_environment() == "government" else "AzurePublicCloud"


def _config_source() -> str:
    """Where the subscription list in front of the operator came from."""
    if utils.get_auto_subscriptions():
        return "env (STRATUSSCAN_SUBSCRIPTIONS)"
    if utils.config_path().exists():
        return "config.json"
    return "auto-discovered"


def _print_status_panel(subs: list) -> None:
    active = subs[0][1] if len(subs) == 1 else f"{len(subs)} active"
    cli_ui.print_panel(
        "StratusScanCLI-Azure — Azure Resource Exporter",
        [
            ("Version", utils.get_version()),
            ("Environment", _environment_label()),
            ("Subscriptions", f"{len(subs)}  ({active})"),
            ("Config source", _config_source()),
            ("Python", sys.version.split()[0]),
        ],
    )


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
        f"{primary[0][1]} only  (default subscription — recommended)",
        f"All {len(subs)} subscriptions  (slower — may time out in Cloud Shell)",
    ]
    choice = cli_ui.prompt_menu(
        "RUN ALL — SELECT SCOPE",
        options,
        allow_back=True,
    )
    if choice == cli_ui.BACK:
        return None
    if choice == 2:
        return subs
    return primary


def _run_exporter_across(path: str, label: str, subs: list) -> list:
    """Run one exporter per subscription; return the outcome rows."""
    run_id = new_run_id()
    outcomes: list = []
    try:
        for sub_id, sub_name in subs:
            _launch(f"{label} [{sub_name}]" if len(subs) > 1 else label, path, sub_id, sub_name, run_id, outcomes)
    except KeyboardInterrupt:
        print("\nInterrupted.")
        _print_status_summary(outcomes)
        sys.exit(130)
    return outcomes


def _status_counts(outcomes: list) -> dict:
    counts: dict = {}
    for outcome in outcomes:
        counts[outcome["Status"]] = counts.get(outcome["Status"], 0) + 1
    return counts


def _print_status_summary(outcomes: list) -> None:
    counts = _status_counts(outcomes)
    parts = [f"{count} {status}" for status, count in sorted(counts.items())]
    print(f"\n{len(outcomes)} exporter run(s): {', '.join(parts) if parts else 'none completed'}")
    problems = [
        f"{o['Exporter']} [{o['Subscription']}]" for o in outcomes if o["Status"] in FAILURE_STATUSES
    ]
    if problems:
        print(f"Needs attention: {', '.join(problems)}")


def has_failures(outcomes: list) -> bool:
    return any(o["Status"] in FAILURE_STATUSES for o in outcomes)


RUN_REPORT_COLUMNS = [
    "Exporter", "Subscription", "Status", "Rows", "Errors", "Duration (s)", "File", "Exit Code",
]


def write_run_report(outcomes: list, label: str, run_id: str) -> str | None:
    """Write output/run-report-{label}-{run_id}.xlsx; return its path (None when there is nothing to report)."""
    if not outcomes:
        return None
    import pandas as pd

    path = utils.output_dir() / f"run-report-{label}-{run_id}.xlsx"
    utils.save_dataframe_to_excel(
        pd.DataFrame(outcomes, columns=RUN_REPORT_COLUMNS), str(path), sheet_name="Run Report"
    )
    return str(path)


def _run_all_exporters(
    exporters: list,
    subs: list,
    package_outputs: bool = False,
    package_label: str | None = None,
) -> list:
    """Run every exporter for every subscription; return the outcome rows (also written to the run report)."""
    run_id = new_run_id()
    label = package_label or "all"
    print(f"\nRunning {len(exporters)} exporter(s) across {_subs_label(subs)}...  (run {run_id})\n")
    outcomes: list = []
    interrupted = False
    tenant_done: set[str] = set()
    try:
        for sub_id, sub_name in subs:
            if len(subs) > 1:
                print(f"=== Subscription: {sub_name} ({sub_id}) ===")
            for exporter_label, path in exporters:
                if path in TENANT_SCOPED_EXPORTERS:
                    if path in tenant_done:
                        continue
                    tenant_done.add(path)
                _launch(exporter_label, path, sub_id, sub_name, run_id, outcomes)
            if len(subs) > 1:
                print()
    except KeyboardInterrupt:
        # subprocess.run forwards the SIGINT to the child and waits for it, so
        # nothing is left running by the time we get here.
        interrupted = True
        print("\nInterrupted — reporting what completed.")

    _print_status_summary(outcomes)
    report_path = write_run_report(outcomes, label, run_id)
    if report_path:
        print(f"Run report → {report_path}")

    if package_outputs and not interrupted:
        _package_outputs(label, run_id)
    if interrupted:
        sys.exit(130)
    return outcomes


def _package_outputs(label: str | None = None, run_id: str | None = None) -> None:
    zip_path = utils.archive_outputs(label, run_id)
    if not zip_path:
        print("\nNo exports found in output/ to package.")
        return
    print(f"\nPackaged exports → {zip_path}")
    print(f"  In Cloud Shell, download it with: download {zip_path}")


# ---------------------------------------------------------------------------
# Menus
# ---------------------------------------------------------------------------

def _run_tier_menu(
    title: str, exporters: list, subs: list, categories: list | None = None
) -> None:
    """One tier submenu. Returns on 'b'; 'x' and 'q' unwind to menu_main as exceptions."""
    headings: dict[int, str] = {}
    if categories:
        exporters, headings = grouped_exporters(exporters, categories)
    while True:
        options = [label for label, _ in exporters] + [f"Run All {title} Exporters"]
        choice = cli_ui.prompt_menu(
            f"{title.upper()} EXPORTERS  ({_subs_label(subs)})",
            options,
            allow_back=True,
            headings=headings,
        )
        if choice == cli_ui.BACK:
            return
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
    _run_tier_menu("Tier 2", TIER2_EXPORTERS, subs, categories=TIER2_CATEGORIES)


def menu_governance(subs: list) -> None:
    _run_tier_menu("Governance", GOVERNANCE_EXPORTERS, subs)


def menu_monitoring(subs: list) -> None:
    _run_tier_menu("Monitoring", MONITORING_EXPORTERS, subs)


MAIN_MENU_OPTIONS = [
    "Tier 1 Exporters   (Core infrastructure: VMs, VNets, Storage, Key Vault, RBAC…)",
    "Tier 2 Exporters   (Workloads: AKS, App Service, SQL, Cosmos DB, Gateways…)",
    "Governance          (Policy, Management Groups, Defender, Advisor…)",
    "Monitoring          (Alerts, Action Groups, Log Analytics…)",
    "Run All Exporters   (Tier 1 + Tier 2 + Governance + Monitoring)",
    "Package Outputs     (zip all exports for Cloud Shell download)",
    "Configure           (subscription selection, environment settings)",
]


def _main_menu_once(subs: list) -> list:
    """Show the main menu, act on one choice, and return the (possibly re-resolved) subscriptions."""
    choice = cli_ui.prompt_menu(
        f"STRATUSSCAN MAIN MENU  ({_subs_label(subs)})",
        MAIN_MENU_OPTIONS,
        allow_back=False,
    )
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
                ALL_EXPORTERS, target, package_outputs=True, package_label="all",
            )
    elif choice == 6:
        _package_outputs()
    elif choice == 7:
        subprocess.run([sys.executable, str(Path(__file__).parent / "configure.py")])
        # configure.py wrote config.json in another process: drop the cached copy
        # (not the whole module — that would reset the credential and logger too)
        # and re-resolve the active subscriptions from it.
        utils.reload_config()
        subs = _active_subscriptions() or subs
    return subs


def menu_main(subs: list) -> None:
    _print_status_panel(subs)
    if len(subs) > 1:
        print(f"  {len(subs)} subscriptions available:")
        for _, sname in subs:
            print(f"    • {sname}")
        print("  (Run All scans one by default — choose scope when prompted.)")
    while True:
        try:
            subs = _main_menu_once(subs)
        except cli_ui.BackToMain:
            continue
        except cli_ui.QuitRequested:
            print("Goodbye.")
            sys.exit(0)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def _environment_label_or_exit() -> str:
    try:
        return _environment_label()
    except ValueError as exc:
        print(f"ERROR: {exc}")
        sys.exit(2)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="stratusscan",
        description="StratusScanCLI-Azure — export Azure resource inventories to Excel",
    )
    parser.add_argument(
        "--version", action="version",
        version=f"StratusScanCLI-Azure {utils.get_version()}",
    )
    parser.add_argument(
        "--list", action="store_true",
        help="list every tier and exporter name, then exit",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="validate the environment and credentials, report what would run, then exit",
    )
    parser.add_argument(
        "--run-all", action="store_true",
        help="run every exporter non-interactively",
    )
    parser.add_argument(
        "--tier", action="append", choices=sorted(TIERS), metavar="TIER",
        help=f"run one tier non-interactively (repeatable): {', '.join(sorted(TIERS))}",
    )
    parser.add_argument(
        "--exporter", action="append", metavar="NAME",
        help="run one exporter non-interactively (repeatable); NAME as shown by --list",
    )
    parser.add_argument(
        "--subscriptions", metavar="IDS",
        help="comma-separated subscription IDs, or 'all' (default: the default subscription)",
    )
    parser.add_argument(
        "--no-zip", action="store_true",
        help="skip zipping this run's exports",
    )
    parser.add_argument(
        "--timeout", type=int, metavar="SECONDS",
        help=f"per-exporter timeout (default: {DEFAULT_EXPORTER_TIMEOUT_S})",
    )
    parser.add_argument(
        "--verbose", action="store_true",
        help="show INFO-level progress on the console (the log file always has it)",
    )
    return parser


def _print_exporter_list() -> None:
    print(f"\nStratusScanCLI-Azure {utils.get_version()} — exporters")
    for key, (title, exporters) in TIERS.items():
        print(f"\n{title}  (--tier {key})  —  {len(exporters)} exporter(s)")
        for label, path in exporters:
            print(f"  {exporter_name(path):<34}{label}")
    print(f"\n{len(ALL_EXPORTERS)} exporters total. Run one with: --exporter NAME")


def _selected_exporters(args: argparse.Namespace) -> list:
    """The exporters the flags ask for, in tier order then --exporter order, deduped."""
    if args.run_all:
        return list(ALL_EXPORTERS)
    chosen: list = []
    for key in args.tier or []:
        for entry in TIERS[key][1]:
            if entry not in chosen:
                chosen.append(entry)
    for entry in resolve_exporters(args.exporter or []):
        if entry not in chosen:
            chosen.append(entry)
    return chosen


def _package_label(args: argparse.Namespace) -> str:
    if args.run_all:
        return "all"
    if args.tier and len(args.tier) == 1 and not args.exporter:
        return args.tier[0]
    return "selected"


def _requested_subscriptions(args: argparse.Namespace, active: list) -> list:
    """
    Resolve --subscriptions. Without it the target is today's Run All default —
    the primary subscription — not every accessible one.
    """
    raw = (args.subscriptions or "").strip()
    if not raw:
        return _primary_subscription(active)
    if raw.lower() == "all":
        return active
    ids = [part.strip() for part in raw.split(",") if part.strip()]
    by_id = dict(active)
    return [(sub_id, by_id.get(sub_id) or utils.get_subscription_name(sub_id)) for sub_id in ids]


def _resolve_active(auto_ids: list[str] | None = None) -> list:
    if auto_ids:
        return [(sid, utils.get_subscription_name(sid)) for sid in auto_ids]
    return _active_subscriptions() or _autodiscover_subscriptions()


def _run_dry_run(args: argparse.Namespace, selected: list | None = None) -> None:
    """Validate the environment and credentials, print what a real run would do, exit."""
    print("\nStratusScanCLI-Azure — dry run")
    print("=" * 64)
    print(f"  [ok] Environment: {_environment_label_or_exit()}")

    try:
        discovered = utils.list_subscriptions()
    except (utils.AzureAccessError, ImportError) as exc:
        print("  [!!] Credentials: not usable")
        print(f"       {exc}")
        hint = getattr(exc, "hint", "")
        if hint:
            print(f"       {hint}")
        print("\nDry run failed. Nothing was run.")
        sys.exit(1)

    print(f"  [ok] Credentials: valid — {len(discovered)} subscription(s) visible")

    active = [(s["id"], s.get("name", s["id"])) for s in discovered if s.get("id")]
    active = _active_subscriptions() or active
    targets = _requested_subscriptions(args, active)
    exporters = selected or list(ALL_EXPORTERS)

    print(f"  Target subscriptions: {len(targets)}")
    for sub_id, sub_name in targets:
        print(f"    • {sub_name} ({sub_id})")
    print(f"  Exporters that would run: {len(exporters)}")
    print(f"  Output directory: {utils.output_dir()}")
    print(f"  Zip this run: {'no' if args.no_zip else 'yes'}")
    print("\nNothing was run.")
    sys.exit(0)


def _run_headless(args: argparse.Namespace, exporters: list) -> None:
    """Non-interactive run through the same path as Run All: run id, manifest, report, zip."""
    raw = (args.subscriptions or "").strip()
    if raw and raw.lower() != "all":
        # Explicit IDs need no discovery call — take them at face value.
        targets = _requested_subscriptions(args, _active_subscriptions())
    else:
        # No --subscriptions: STRATUSSCAN_SUBSCRIPTIONS still applies, as it is the
        # lower-precedence source, and naming subscriptions there means scan them all.
        auto_ids = [] if raw else utils.get_auto_subscriptions()
        active = _resolve_active(auto_ids)
        targets = active if auto_ids else _requested_subscriptions(args, active)
    if not targets:
        print("\nNo subscriptions to scan (none set, configured, or discoverable).")
        sys.exit(1)

    print(f"\nScanning {_subs_label(targets)}")
    outcomes = _run_all_exporters(
        exporters,
        targets,
        package_outputs=not args.no_zip,
        package_label=_package_label(args),
    )
    sys.exit(1 if has_failures(outcomes) else 0)


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(sys.argv[1:] if argv is None else argv)

    if args.list:
        _print_exporter_list()
        sys.exit(0)

    bootstrap.ensure_dependencies()
    utils.setup_logging("main-menu", log_to_file=True)
    if args.verbose:
        utils.set_console_level(logging.INFO)
    utils.log_script_start("stratusscan.py", "StratusScan Main Menu")
    utils.log_system_info()

    # An explicit flag beats the environment, so this is set before anything reads it.
    if args.timeout is not None:
        os.environ["STRATUSSCAN_EXPORTER_TIMEOUT"] = str(args.timeout)

    env_label = _environment_label_or_exit()

    try:
        selected = _selected_exporters(args)
    except UnknownExporterError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        print("Valid names (also accepted: the menu label):", file=sys.stderr)
        for name in exporter_names():
            print(f"  {name}", file=sys.stderr)
        sys.exit(2)

    if args.dry_run:
        _run_dry_run(args, selected)

    if selected:
        _run_headless(args, selected)

    if utils.is_auto_run():
        subs = _resolve_active(utils.get_auto_subscriptions())
        if not subs:
            print("\nNo subscriptions to scan (none set, configured, or discoverable).")
            sys.exit(1)
        print(f"\nAuto-run: scanning {_subs_label(subs)}")
        outcomes = _run_all_exporters(
            ALL_EXPORTERS, subs, package_outputs=not args.no_zip, package_label="all",
        )
        sys.exit(1 if has_failures(outcomes) else 0)

    subs = _active_subscriptions() or _autodiscover_subscriptions()
    if not subs:
        print("\nNo accessible subscriptions found.")
        print(f"  Sign-in worked, but no enabled subscription is visible in {env_label}.")
        print("  Check the account and tenant (`az account list`), or set AZURE_ENVIRONMENT if the cloud is wrong.")
        sys.exit(1)
    menu_main(subs)


if __name__ == "__main__":
    main()
