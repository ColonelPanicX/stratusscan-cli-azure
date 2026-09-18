#!/usr/bin/env python3
"""StratusScanCLI-Azure — Diagnostic Settings Cross-Resource Audit Export

One diagnostic_settings.list call per resource. A resource type that answers
ResourceTypeNotSupported is remembered and its remaining resources are skipped
without a call. 403 and 429 answers are classified on the Summary sheet and
recorded on the Errors sheet (PARTIAL). The subscription's own activity-log
diagnostic settings land on an "Activity Log" sheet, present even when empty.
"""

import sys
from pathlib import Path

try:
    import utils
except ImportError:
    sys.path.append(str(Path(__file__).parent.parent))
    import utils

import pandas as pd
from azure.core.exceptions import HttpResponseError

utils.setup_logging("diagnostic-settings-export")
utils.log_script_start("diagnostic_settings_export.py", "Diagnostic Settings Cross-Resource Audit Export")

log = utils.get_logger()

PROGRESS_EVERY = 50
UNSUPPORTED_CODE = "ResourceTypeNotSupported"

ACTIVITY_LOG_COLUMNS = [
    "Setting Name", "Log Categories", "Destination", "Workspace ID",
    "Storage Account ID", "Event Hub Authorization Rule ID", "Marketplace Partner ID",
]


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


def failure_status(exc: HttpResponseError) -> str:
    code = utils.error_code(exc)
    if code == UNSUPPORTED_CODE:
        return "Unsupported"
    status = getattr(exc, "status_code", None)
    if status == 403:
        return f"Forbidden ({code})"
    if status == 429:
        return f"Throttled ({code})"
    return f"Error ({code})"


def _activity_log_row(setting) -> dict:
    return {
        "Setting Name": utils.s(getattr(setting, "name", None)),
        "Log Categories": _enabled_log_categories(setting),
        "Destination": _destinations(setting),
        "Workspace ID": utils.s(getattr(setting, "workspace_id", None)),
        "Storage Account ID": utils.s(getattr(setting, "storage_account_id", None)),
        "Event Hub Authorization Rule ID": utils.s(getattr(setting, "event_hub_authorization_rule_id", None)),
        "Marketplace Partner ID": utils.s(getattr(setting, "marketplace_partner_id", None)),
    }


def collect_activity_log_settings(monitor, subscription_id: str, errors: list) -> list:
    """Subscription-level diagnostic settings (activity log export); the client is already bound to the subscription."""
    log.info("Listing activity-log diagnostic settings for subscription %s", subscription_id)
    try:
        settings = list(monitor.subscription_diagnostic_settings.list())
    except HttpResponseError as exc:
        errors.append(utils.error_record(subscription_id, "subscription_diagnostic_settings.list", exc))
        log.warning("Activity-log diagnostic settings unavailable: %s", exc)
        return []
    return [_activity_log_row(s) for s in settings]


def audit_resources(monitor, resources: list, errors: list) -> tuple:
    """Return (summary_rows, detail_rows); unsupported resource types are memoized after their first answer."""
    summary_rows = []
    detail_rows = []
    unsupported_types: set = set()
    total = len(resources)

    for index, r in enumerate(resources, start=1):
        rg = utils.extract_resource_group(r.id)
        resource_type = utils.s(r.type)
        settings: list = []
        if resource_type.lower() in unsupported_types:
            status = "Unsupported (type)"
        else:
            try:
                settings = list(monitor.diagnostic_settings.list(r.id))
                status = "Yes" if settings else "No"
            except HttpResponseError as exc:
                status = failure_status(exc)
                if status == "Unsupported":
                    unsupported_types.add(resource_type.lower())
                else:
                    errors.append(utils.error_record(utils.s(r.id), "diagnostic_settings.list", exc))
                log.warning("Diagnostic settings unavailable for %s: %s", r.id, utils.error_code(exc))

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

        if index % PROGRESS_EVERY == 0 or index == total:
            print(f"  audited {index}/{total} resources", flush=True)

    if unsupported_types:
        log.info("Skipped remaining resources of %d unsupported type(s)", len(unsupported_types))
    return summary_rows, detail_rows


def main(subscription_id: str, subscription_name: str) -> utils.ExportResult:
    environment = utils.detect_environment()
    if not utils.is_service_available_in_environment("monitor", environment):
        sys.exit(0)

    resources = collect_resources(subscription_id)
    if not resources:
        raise utils.NoResourcesFound("resources")

    monitor = utils.get_azure_client("monitor", subscription_id)
    log.info("Auditing diagnostic settings across %d resources (one API call each)", len(resources))

    errors: list = []
    summary_rows, detail_rows = audit_resources(monitor, resources, errors)
    activity_log_rows = collect_activity_log_settings(monitor, subscription_id, errors)

    sheets = {"Summary": pd.DataFrame(summary_rows)}
    if detail_rows:
        sheets["Diagnostic Settings"] = pd.DataFrame(detail_rows)
    sheets["Activity Log"] = pd.DataFrame(activity_log_rows, columns=ACTIVITY_LOG_COLUMNS)

    filename = utils.create_export_filename(subscription_name, "diagnostic-settings", "all")
    utils.save_multiple_dataframes_to_excel(sheets, filename, errors=errors)

    enabled = sum(1 for row in summary_rows if row["Has Diagnostics"] == "Yes")
    print(
        f"Audited {len(summary_rows)} resource(s): {enabled} with diagnostics, "
        f"{len(detail_rows)} setting(s), {len(activity_log_rows)} activity-log setting(s) → {filename}"
    )
    log.info(
        "Export complete: %d resources audited, %d settings, %d activity-log settings",
        len(summary_rows), len(detail_rows), len(activity_log_rows),
    )
    return utils.ExportResult(rows=len(summary_rows), filename=filename, errors=errors)


if __name__ == "__main__":
    import runner

    runner.run_exporter(main, "diagnostic-settings")
