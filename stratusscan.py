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

import datetime
import os
import subprocess
import sys
import time
from pathlib import Path

# Ensure local modules are importable from the project root.
sys.path.insert(0, str(Path(__file__).parent))

import bootstrap

try:
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
    stem = Path(script_rel_path).stem
    if stem.endswith("_export"):
        stem = stem[: -len("_export")]
    return stem.replace("_", "-")


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

    out_dir = Path(utils.__file__).parent / "output"
    out_dir.mkdir(exist_ok=True)
    path = out_dir / f"run-report-{label}-{run_id}.xlsx"
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
    try:
        for sub_id, sub_name in subs:
            if len(subs) > 1:
                print(f"=== Subscription: {sub_name} ({sub_id}) ===")
            for exporter_label, path in exporters:
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

def _environment_label_or_exit() -> str:
    try:
        environment = utils.detect_environment()
    except ValueError as exc:
        print(f"ERROR: {exc}")
        sys.exit(2)
    return "AzureUSGovernment" if environment == "government" else "AzurePublicCloud"


def main() -> None:
    bootstrap.ensure_dependencies()
    utils.setup_logging("main-menu", log_to_file=True)
    utils.log_script_start("stratusscan.py", "StratusScan Main Menu")
    utils.log_system_info()

    env_label = _environment_label_or_exit()

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
        outcomes = _run_all_exporters(
            TIER1_EXPORTERS + TIER2_EXPORTERS + GOVERNANCE_EXPORTERS + MONITORING_EXPORTERS,
            subs,
            package_outputs=True,
            package_label="all",
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
