#!/usr/bin/env python3
"""StratusScanCLI-Azure — Defender for Cloud Security Alerts Export

Alerts are listed at subscription scope; the client is already bound to the
subscription, so alerts.list() takes no scope argument.

The alert's `entities` and `extendedProperties` bags are deliberately not
exported. Both are open, detection-specific structures that routinely carry file
paths, host names, user names, command lines and process arguments captured from
the detection, so exporting them wholesale would put incident detail into a
workbook that circulates as audit evidence. The affected resource, alert type
and remediation steps are exported instead; open the Alert URI for the detail.
"""

import sys
from pathlib import Path
from typing import Any

try:
    import utils
except ImportError:
    sys.path.append(str(Path(__file__).parent.parent))
    import utils

import pandas as pd

log = utils.get_logger()


def _resource_type_from_id(resource_id: str) -> str:
    parts = [p for p in resource_id.split("/") if p]
    lowered = [p.lower() for p in parts]
    if "providers" in lowered:
        p = len(lowered) - 1 - lowered[::-1].index("providers")
        if p + 1 >= len(parts):
            return ""
        return "/".join([parts[p + 1]] + parts[p + 2::2])
    if len(lowered) >= 4 and lowered[0] == "subscriptions" and lowered[2] == "resourcegroups":
        return "Microsoft.Resources/subscriptions/resourceGroups"
    if len(lowered) == 2 and lowered[0] == "subscriptions":
        return "Microsoft.Resources/subscriptions"
    return ""


def azure_resource_id(alert) -> str:
    """First AzureResource identifier; the other identifier kind points at a Log Analytics workspace."""
    for identifier in getattr(alert, "resource_identifiers", None) or []:
        resource_id = utils.s(getattr(identifier, "azure_resource_id", None))
        if resource_id:
            return resource_id
    return ""


def _iso(value: Any) -> str:
    return value.isoformat() if hasattr(value, "isoformat") else utils.s(value)


def _build_row(alert) -> dict[str, Any]:
    resource_id = azure_resource_id(alert)
    steps = getattr(alert, "remediation_steps", None) or []
    return {
        "Alert Display Name": utils.s(getattr(alert, "alert_display_name", None)),
        "Severity": utils.s(getattr(alert, "severity", None)),
        "Status": utils.s(getattr(alert, "status", None)),
        "Intent": utils.s(getattr(alert, "intent", None)),
        "Detected Time": _iso(getattr(alert, "time_generated_utc", None)),
        "Start Time": _iso(getattr(alert, "start_time_utc", None)),
        "End Time": _iso(getattr(alert, "end_time_utc", None)),
        "Resource ID": resource_id,
        "Resource Name": resource_id.rstrip("/").split("/")[-1] if resource_id else "",
        "Resource Type": _resource_type_from_id(resource_id),
        "Compromised Entity": utils.s(getattr(alert, "compromised_entity", None)),
        "Description": utils.s(getattr(alert, "description", None)),
        "Remediation Steps": " | ".join(utils.s(step) for step in steps),
        "Alert Type": utils.s(getattr(alert, "alert_type", None)),
        "Vendor": utils.s(getattr(alert, "vendor_name", None)),
        "Product Name": utils.s(getattr(alert, "product_name", None)),
        "Is Incident": "Yes" if getattr(alert, "is_incident", False) else "No",
        "System Alert ID": utils.s(getattr(alert, "system_alert_id", None)),
        "Alert URI": utils.s(getattr(alert, "alert_uri", None)),
    }


def collect_alerts(subscription_id: str) -> list[dict[str, Any]]:
    client = utils.get_azure_client("security", subscription_id)
    log.info("Listing Defender for Cloud alerts for subscription %s", subscription_id)
    return [_build_row(alert) for alert in client.alerts.list()]


def main(subscription_id: str, subscription_name: str) -> utils.ExportResult:
    environment = utils.detect_environment()
    if not utils.is_service_available_in_environment("security", environment):
        sys.exit(0)

    rows = collect_alerts(subscription_id)
    if not rows:
        raise utils.NoResourcesFound("security alerts")

    df = pd.DataFrame(rows)
    filename = utils.create_export_filename(subscription_name, "defender-alerts", "all")
    utils.save_dataframe_to_excel(df, filename, sheet_name="Security Alerts")
    print(f"Exported {len(rows)} security alert(s) → {filename}")
    log.info("Export complete: %d security alerts", len(rows))
    return utils.ExportResult(rows=len(rows), filename=filename, errors=[])


if __name__ == "__main__":
    import runner

    runner.run_exporter(main, "defender-alerts")
