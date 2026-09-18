#!/usr/bin/env python3
"""StratusScanCLI-Azure — Metric Alerts & Activity Log Alerts Export"""

import sys
from pathlib import Path
from typing import Any

try:
    import utils
except ImportError:
    sys.path.append(str(Path(__file__).parent.parent))
    import utils

import pandas as pd

utils.setup_logging("metric-alerts-export")
utils.log_script_start("metric_alerts_export.py", "Metric Alerts & Activity Log Alerts Export")

log = utils.get_logger()

_WEBTEST_ODATA_TYPE = "Microsoft.Azure.Monitor.WebtestLocationAvailabilityCriteria"
_DYNAMIC_CRITERION_TYPE = "DynamicThresholdCriterion"


def _cell(value: Any) -> Any:
    """Keep numeric zero: only None becomes blank. Whole-number floats from the API render as ints."""
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return value


def _format_duration(value: Any) -> str:
    if value is None:
        return ""
    if hasattr(value, "total_seconds"):
        return f"{int(value.total_seconds() / 60)}m"
    return utils.s(value)


def _format_dimensions(dimensions) -> str:
    if not dimensions:
        return ""
    parts = []
    for d in dimensions:
        values = getattr(d, "values", None) or []
        parts.append(f"{utils.s(getattr(d, 'name', None))} {utils.s(getattr(d, 'operator', None))} "
                     f"{','.join(utils.s(v) for v in values)}")
    return " [" + "; ".join(parts) + "]"


def _format_metric_criterion(crit) -> str:
    metric = utils.s(getattr(crit, "metric_name", None))
    operator = utils.s(getattr(crit, "operator", None))
    aggregation = utils.s(getattr(crit, "time_aggregation", None))
    subject = f"{aggregation}({metric})" if aggregation else metric
    dimensions = _format_dimensions(getattr(crit, "dimensions", None))

    if utils.s(getattr(crit, "criterion_type", None)) == _DYNAMIC_CRITERION_TYPE:
        sensitivity = utils.s(getattr(crit, "alert_sensitivity", None))
        periods = getattr(crit, "failing_periods", None)
        min_failing = _cell(getattr(periods, "min_failing_periods_to_alert", None))
        evaluation = _cell(getattr(periods, "number_of_evaluation_periods", None))
        return f"{subject} {operator} dynamic(sensitivity={sensitivity}, failing {min_failing}/{evaluation}){dimensions}"

    threshold = _cell(getattr(crit, "threshold", None))
    return f"{subject} {operator} {threshold}{dimensions}"


def _format_criteria(criteria) -> str:
    if not criteria:
        return ""
    if utils.s(getattr(criteria, "odata_type", None)) == _WEBTEST_ODATA_TYPE:
        web_test = utils.s(getattr(criteria, "web_test_id", None)).split("/")[-1]
        failed = _cell(getattr(criteria, "failed_location_count", None))
        return f"Webtest {web_test}: failedLocationCount={failed}"
    parts = [_format_metric_criterion(crit) for crit in getattr(criteria, "all_of", None) or []]
    return "; ".join(parts) if parts else utils.s(getattr(criteria, "odata_type", None))


def _format_action_groups(actions) -> str:
    if not actions:
        return ""
    names = []
    for a in actions:
        ag_id = utils.s(getattr(a, "action_group_id", None))
        names.append(ag_id.split("/")[-1] if ag_id else "")
    return ", ".join(n for n in names if n)


def _format_scopes(scopes) -> str:
    if not scopes:
        return ""
    return ", ".join(s.split("/")[-1] if "/" in s else s for s in scopes)


def _yes_no(value: Any) -> str:
    if value is None:
        return ""
    return "Yes" if value else "No"


def _build_metric_alert_row(alert) -> dict:
    alert_id = utils.s(getattr(alert, "id", None))
    scopes = getattr(alert, "scopes", None) or []
    return {
        "Alert Name": utils.s(getattr(alert, "name", None)),
        "Resource Group": utils.extract_resource_group(alert_id),
        "Severity": _cell(getattr(alert, "severity", None)),
        "Enabled": "Yes" if getattr(alert, "enabled", False) else "No",
        "Target Resource": _format_scopes(scopes),
        "Condition": _format_criteria(getattr(alert, "criteria", None)),
        "Window Size": _format_duration(getattr(alert, "window_size", None)),
        "Action Groups": _format_action_groups(getattr(alert, "actions", None)),
        "Description": utils.s(getattr(alert, "description", None)),
        "Evaluation Frequency": _format_duration(getattr(alert, "evaluation_frequency", None)),
        "Auto Mitigate": _yes_no(getattr(alert, "auto_mitigate", None)),
        "Scope IDs": "; ".join(utils.s(s) for s in scopes),
    }


def collect_metric_alerts(subscription_id: str) -> list:
    client = utils.get_azure_client("monitor", subscription_id)
    log.info("Listing metric alert rules for subscription %s", subscription_id)

    rows = []
    try:
        for alert in client.metric_alerts.list_by_subscription():
            rows.append(_build_metric_alert_row(alert))
    except Exception as e:
        log.warning("Failed to list metric alerts: %s", e)

    return rows


def collect_activity_log_alerts(subscription_id: str) -> list:
    client = utils.get_azure_client("monitor", subscription_id)
    log.info("Listing activity log alert rules for subscription %s", subscription_id)

    rows = []
    try:
        for alert in client.activity_log_alerts.list_by_subscription_id():
            alert_id = getattr(alert, "id", "") or ""
            rg = utils.extract_resource_group(alert_id)

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
    sub_id, sub_name = utils.resolve_target_subscription()
    if not sub_id:
        print("ERROR: No subscription configured. Run configure.py first.")
        sys.exit(1)
    main(sub_id, sub_name)
