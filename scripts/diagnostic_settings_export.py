#!/usr/bin/env python3
"""StratusScanCLI-Azure — Diagnostic Settings Cross-Resource Audit Export"""

import sys
from pathlib import Path

try:
    import utils
except ImportError:
    sys.path.append(str(Path(__file__).parent.parent))
    import utils

import pandas as pd

utils.setup_logging("diagnostic-settings-export")
utils.log_script_start("diagnostic_settings_export.py", "Diagnostic Settings Cross-Resource Audit Export")

log = utils.get_logger()


def collect_resources(subscription_id: str) -> list:
    client = utils.get_azure_client("resource", subscription_id)
    log.info("Listing all resources in subscription %s", subscription_id)
    return list(client.resources.list())


def _enabled_log_categories(setting) -> str:
    cats = []
    for entry in getattr(setting, "logs", None) or []:
        if getattr(entry, "enabled", False):
            cats.append(getattr(entry, "category", None) or getattr(entry, "category_group", None) or "")
    return ", ".join(c for c in cats if c)


def _metrics_enabled(setting) -> bool:
    return any(getattr(m, "enabled", False) for m in (getattr(setting, "metrics", None) or []))


def _destinations(setting) -> str:
    dests = []
    ws = getattr(setting, "workspace_id", "") or ""
    if ws:
        dests.append(f"LogAnalytics:{ws.split('/')[-1]}")
    sa = getattr(setting, "storage_account_id", "") or ""
    if sa:
        dests.append(f"Storage:{sa.split('/')[-1]}")
    eh = getattr(setting, "event_hub_name", "") or getattr(setting, "event_hub_authorization_rule_id", "") or ""
    if eh:
        dests.append(f"EventHub:{eh.split('/')[-1]}")
    return ", ".join(dests)


def _max_retention(setting) -> str:
    days = []
    for entry in (getattr(setting, "logs", None) or []) + (getattr(setting, "metrics", None) or []):
        policy = getattr(entry, "retention_policy", None)
        if policy and getattr(policy, "enabled", False) and getattr(policy, "days", None):
            days.append(policy.days)
    return str(max(days)) if days else ""


def main(subscription_id: str, subscription_name: str) -> None:
    environment = utils.detect_environment()
    if not utils.is_service_available_in_environment("monitor", environment):
        sys.exit(0)

    resources = collect_resources(subscription_id)
    if not resources:
        print("No resources found.")
        return

    monitor = utils.get_azure_client("monitor", subscription_id)
    log.info("Auditing diagnostic settings across %d resources (one API call each)", len(resources))

    summary_rows = []
    detail_rows = []

    for r in resources:
        rg = r.id.split("/resourceGroups/")[1].split("/")[0] if r.id and "/resourceGroups/" in r.id else ""
        try:
            settings = list(monitor.diagnostic_settings.list(r.id).value or [])
            status = "Yes" if settings else "No"
        except Exception:
            settings = []
            status = "Unsupported/Error"

        summary_rows.append({
            "Resource Name": r.name,
            "Resource Type": r.type,
            "Resource Group": rg,
            "Has Diagnostics": status,
            "Setting Count": len(settings),
        })

        for s in settings:
            detail_rows.append({
                "Resource Name": r.name,
                "Resource Type": r.type,
                "Resource Group": rg,
                "Setting Name": getattr(s, "name", "") or "",
                "Log Categories": _enabled_log_categories(s),
                "Metrics Enabled": "Yes" if _metrics_enabled(s) else "No",
                "Destination": _destinations(s),
                "Retention Days": _max_retention(s),
            })

    sheets = {"Summary": pd.DataFrame(summary_rows)}
    if detail_rows:
        sheets["Diagnostic Settings"] = pd.DataFrame(detail_rows)

    filename = utils.create_export_filename(subscription_name, "diagnostic-settings", "all")
    utils.save_multiple_dataframes_to_excel(sheets, filename)

    enabled = sum(1 for row in summary_rows if row["Has Diagnostics"] == "Yes")
    print(f"Audited {len(summary_rows)} resource(s): {enabled} with diagnostics, {len(detail_rows)} setting(s) → {filename}")
    log.info("Export complete: %d resources audited, %d settings", len(summary_rows), len(detail_rows))


if __name__ == "__main__":
    sub_id, sub_name = utils.resolve_target_subscription()
    if not sub_id:
        print("ERROR: No subscription configured. Run configure.py first.")
        sys.exit(1)
    main(sub_id, sub_name)
