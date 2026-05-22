#!/usr/bin/env python3
"""StratusScanCLI-Azure — Metric Alerts & Activity Log Alerts Export"""

import sys
from pathlib import Path

try:
    import utils
except ImportError:
    sys.path.append(str(Path(__file__).parent.parent.parent))
    import utils

import pandas as pd

utils.setup_logging("metric-alerts-export")
utils.log_script_start("metric_alerts_export.py", "Metric Alerts & Activity Log Alerts Export")

log = utils.get_logger()


def _format_criteria(criteria) -> str:
    if not criteria:
        return ""
    parts = []
    metric_triggers = getattr(criteria, "all_of", None) or []
    for crit in metric_triggers:
        metric = getattr(crit, "metric_name", "") or ""
        operator = getattr(crit, "operator", "") or ""
        threshold = getattr(crit, "threshold", "") or ""
        if metric:
            parts.append(f"{metric} {operator} {threshold}")
    return "; ".join(parts) if parts else str(criteria)


def _format_action_groups(actions) -> str:
    if not actions:
        return ""
    names = []
    for a in actions:
        ag_id = getattr(a, "action_group_id", "") or ""
        names.append(ag_id.split("/")[-1] if ag_id else "")
    return ", ".join(n for n in names if n)


def _format_scopes(scopes) -> str:
    if not scopes:
        return ""
    return ", ".join(s.split("/")[-1] if "/" in s else s for s in scopes)


def collect_metric_alerts(subscription_id: str) -> list:
    client = utils.get_azure_client("monitor", subscription_id)
    log.info("Listing metric alert rules for subscription %s", subscription_id)

    rows = []
    try:
        for alert in client.metric_alerts.list_by_subscription():
            rg = ""
            alert_id = getattr(alert, "id", "") or ""
            if "/resourceGroups/" in alert_id:
                rg = alert_id.split("/resourceGroups/")[1].split("/")[0]

            window = getattr(alert, "window_size", "") or ""
            if hasattr(window, "total_seconds"):
                mins = int(window.total_seconds() / 60)
                window = f"{mins}m"

            rows.append({
                "Alert Name": getattr(alert, "name", "") or "",
                "Resource Group": rg,
                "Severity": getattr(alert, "severity", "") or "",
                "Enabled": "Yes" if getattr(alert, "enabled", False) else "No",
                "Target Resource": _format_scopes(getattr(alert, "scopes", None)),
                "Condition": _format_criteria(getattr(alert, "criteria", None)),
                "Window Size": str(window),
                "Action Groups": _format_action_groups(getattr(alert, "actions", None)),
                "Description": getattr(alert, "description", "") or "",
            })
    except Exception as e:
        log.warning("Failed to list metric alerts: %s", e)

    return rows


def collect_activity_log_alerts(subscription_id: str) -> list:
    client = utils.get_azure_client("monitor", subscription_id)
    log.info("Listing activity log alert rules for subscription %s", subscription_id)

    rows = []
    try:
        for alert in client.activity_log_alerts.list_by_subscription_id():
            rg = ""
            alert_id = getattr(alert, "id", "") or ""
            if "/resourceGroups/" in alert_id:
                rg = alert_id.split("/resourceGroups/")[1].split("/")[0]

            conditions = []
            condition = getattr(alert, "condition", None)
            if condition:
                all_of = getattr(condition, "all_of", None) or []
                for c in all_of:
                    field = getattr(c, "field", "") or ""
                    equals = getattr(c, "equals", "") or ""
                    if field:
                        conditions.append(f"{field}={equals}")

            actions_obj = getattr(alert, "actions", None)
            action_groups = []
            if actions_obj:
                ag_list = getattr(actions_obj, "action_groups", None) or []
                for ag in ag_list:
                    ag_id = getattr(ag, "action_group_id", "") or ""
                    action_groups.append(ag_id.split("/")[-1] if ag_id else "")

            rows.append({
                "Alert Name": getattr(alert, "name", "") or "",
                "Resource Group": rg,
                "Enabled": "Yes" if getattr(alert, "enabled", True) else "No",
                "Scopes": _format_scopes(getattr(alert, "scopes", None)),
                "Conditions": "; ".join(conditions),
                "Action Groups": ", ".join(g for g in action_groups if g),
                "Description": getattr(alert, "description", "") or "",
            })
    except Exception as e:
        log.warning("Failed to list activity log alerts: %s", e)

    return rows


def main(subscription_id: str, subscription_name: str) -> None:
    environment = utils.detect_environment()
    if not utils.is_service_available_in_environment("resource", environment):
        sys.exit(0)

    metric_rows = collect_metric_alerts(subscription_id)
    activity_rows = collect_activity_log_alerts(subscription_id)

    if not metric_rows and not activity_rows:
        print("No metric or activity log alerts found.")
        return

    sheets = {}
    if metric_rows:
        sheets["Metric Alerts"] = pd.DataFrame(metric_rows)
    if activity_rows:
        sheets["Activity Log Alerts"] = pd.DataFrame(activity_rows)

    filename = utils.create_export_filename(subscription_name, "metric-alerts", "all")
    utils.save_multiple_dataframes_to_excel(sheets, filename)
    print(f"Exported {len(metric_rows)} metric alert(s), {len(activity_rows)} activity log alert(s) → {filename}")
    log.info("Export complete: %d metric alerts, %d activity log alerts", len(metric_rows), len(activity_rows))


if __name__ == "__main__":
    cfg = utils.get_config()
    sub_id = cfg.get("default_subscription_id", "")
    sub_name = utils.get_subscription_name(sub_id)
    if not sub_id:
        print("ERROR: No subscription configured. Run configure.py first.")
        sys.exit(1)
    main(sub_id, sub_name)
