#!/usr/bin/env python3
"""StratusScanCLI-Azure — Activity Log Export Settings Export

Subscription-level diagnostic settings: where — and whether — the Azure activity
log is exported beyond its 90-day platform retention. This is the audit-trail
question an assessor asks first, so a subscription with no settings is reported
as a finding row in the workbook rather than as an empty export.

The Assessment sheet answers it per category: the Administrative, Security and
Policy categories are the ones that carry control-plane writes, Defender alerts
and policy effect actions.
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

AUDIT_CATEGORIES = ("Administrative", "Security", "Policy")

NO_SETTINGS_FINDING = (
    "FINDING: no subscription diagnostic setting exports the activity log. "
    "Activity log entries are retained for 90 days and then discarded."
)

SETTING_COLUMNS = [
    "Setting Name", "Log Categories", "Destinations", "Workspace ID",
    "Storage Account ID", "Event Hub Namespace", "Event Hub Name",
    "Event Hub Authorization Rule ID", "Marketplace Partner ID", "Assessment",
]
ASSESSMENT_COLUMNS = ["Category", "Exported", "Settings", "Destinations"]


def collect_settings(subscription_id: str) -> list:
    """The monitor client is already bound to the subscription — list() takes no scope."""
    client = utils.get_azure_client("monitor", subscription_id)
    log.info("Listing activity-log diagnostic settings for subscription %s", subscription_id)
    return list(client.subscription_diagnostic_settings.list())


def enabled_categories(setting) -> list[str]:
    categories = []
    for entry in getattr(setting, "logs", None) or []:
        if not getattr(entry, "enabled", False):
            continue
        name = utils.s(getattr(entry, "category", None)) or utils.s(getattr(entry, "category_group", None))
        if name:
            categories.append(name)
    return categories


def _event_hub_namespace(authorization_rule_id: str) -> str:
    parts = [p for p in authorization_rule_id.split("/") if p]
    lowered = [p.lower() for p in parts]
    if "namespaces" in lowered:
        index = lowered.index("namespaces")
        if index + 1 < len(parts):
            return parts[index + 1]
    return ""


def destinations(setting) -> list[str]:
    targets = []
    workspace = utils.s(getattr(setting, "workspace_id", None))
    if workspace:
        targets.append(f"LogAnalytics:{workspace.split('/')[-1]}")
    storage = utils.s(getattr(setting, "storage_account_id", None))
    if storage:
        targets.append(f"Storage:{storage.split('/')[-1]}")
    rule = utils.s(getattr(setting, "event_hub_authorization_rule_id", None))
    hub = utils.s(getattr(setting, "event_hub_name", None))
    if rule or hub:
        targets.append(f"EventHub:{hub or _event_hub_namespace(rule)}")
    partner = utils.s(getattr(setting, "marketplace_partner_id", None))
    if partner:
        targets.append(f"Partner:{partner.split('/')[-1]}")
    return targets


def _setting_assessment(categories: list[str], targets: list[str]) -> str:
    present = [c for c in AUDIT_CATEGORIES if c.lower() in {x.lower() for x in categories}]
    if not present:
        return "No audit category (Administrative, Security, Policy) enabled"
    where = ", ".join(targets) if targets else "no destination configured"
    missing = [c for c in AUDIT_CATEGORIES if c not in present]
    text = f"Exports {', '.join(present)} → {where}"
    if missing:
        text += f"; not exported here: {', '.join(missing)}"
    return text


def _setting_row(setting) -> dict[str, Any]:
    categories = enabled_categories(setting)
    targets = destinations(setting)
    rule = utils.s(getattr(setting, "event_hub_authorization_rule_id", None))
    return {
        "Setting Name": utils.s(getattr(setting, "name", None)),
        "Log Categories": ", ".join(categories),
        "Destinations": ", ".join(targets),
        "Workspace ID": utils.s(getattr(setting, "workspace_id", None)),
        "Storage Account ID": utils.s(getattr(setting, "storage_account_id", None)),
        "Event Hub Namespace": _event_hub_namespace(rule),
        "Event Hub Name": utils.s(getattr(setting, "event_hub_name", None)),
        "Event Hub Authorization Rule ID": rule,
        "Marketplace Partner ID": utils.s(getattr(setting, "marketplace_partner_id", None)),
        "Assessment": _setting_assessment(categories, targets),
    }


def _finding_row() -> dict[str, Any]:
    row = dict.fromkeys(SETTING_COLUMNS, "")
    row["Setting Name"] = "(none)"
    row["Assessment"] = NO_SETTINGS_FINDING
    return row


def build_rows(settings: list) -> list[dict[str, Any]]:
    return [_setting_row(s) for s in settings] or [_finding_row()]


def build_assessment_rows(settings: list) -> list[dict[str, Any]]:
    rows = []
    for category in AUDIT_CATEGORIES:
        carrying = [
            s for s in settings
            if category.lower() in {c.lower() for c in enabled_categories(s)}
        ]
        targets = []
        for setting in carrying:
            targets.extend(t for t in destinations(setting) if t not in targets)
        rows.append({
            "Category": category,
            "Exported": "Yes" if carrying else "No",
            "Settings": ", ".join(utils.s(getattr(s, "name", None)) for s in carrying),
            "Destinations": ", ".join(targets),
        })
    return rows


def main(subscription_id: str, subscription_name: str) -> utils.ExportResult:
    environment = utils.detect_environment()
    if not utils.is_service_available_in_environment("monitor", environment):
        sys.exit(0)

    settings = collect_settings(subscription_id)

    sheets = {
        "Activity Log Settings": pd.DataFrame(build_rows(settings), columns=SETTING_COLUMNS),
        "Assessment": pd.DataFrame(build_assessment_rows(settings), columns=ASSESSMENT_COLUMNS),
    }
    filename = utils.create_export_filename(subscription_name, "activity-log-settings", "all")
    utils.save_multiple_dataframes_to_excel(sheets, filename)

    if settings:
        print(f"Exported {len(settings)} activity-log diagnostic setting(s) → {filename}")
    else:
        print(f"No activity-log diagnostic setting on this subscription — finding written to {filename}")
    log.info("Export complete: %d activity-log diagnostic settings", len(settings))
    return utils.ExportResult(rows=len(settings), filename=filename, errors=[])


if __name__ == "__main__":
    import runner

    runner.run_exporter(main, "activity-log-settings")
