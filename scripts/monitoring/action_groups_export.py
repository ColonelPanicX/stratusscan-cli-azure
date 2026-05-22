#!/usr/bin/env python3
"""StratusScanCLI-Azure — Action Groups Export"""

import sys
from pathlib import Path

try:
    import utils
except ImportError:
    sys.path.append(str(Path(__file__).parent.parent.parent))
    import utils

import pandas as pd

utils.setup_logging("action-groups-export")
utils.log_script_start("action_groups_export.py", "Action Groups Export")

log = utils.get_logger()


def _format_receivers(receivers, name_attr: str, detail_attr: str = "") -> str:
    if not receivers:
        return ""
    parts = []
    for r in receivers:
        name = getattr(r, name_attr, "") or ""
        detail = getattr(r, detail_attr, "") if detail_attr else ""
        if detail:
            parts.append(f"{name} ({detail})")
        else:
            parts.append(name)
    return ", ".join(parts)


def collect_action_groups(subscription_id: str) -> list:
    client = utils.get_azure_client("monitor", subscription_id)
    log.info("Listing action groups for subscription %s", subscription_id)

    rows = []
    try:
        for ag in client.action_groups.list_by_subscription_id():
            rg = ""
            ag_id = getattr(ag, "id", "") or ""
            if "/resourceGroups/" in ag_id:
                rg = ag_id.split("/resourceGroups/")[1].split("/")[0]

            rows.append({
                "Action Group Name": getattr(ag, "name", "") or "",
                "Resource Group": rg,
                "Short Name": getattr(ag, "group_short_name", "") or "",
                "Enabled": "Yes" if getattr(ag, "enabled", True) else "No",
                "Email Receivers": _format_receivers(
                    getattr(ag, "email_receivers", None), "name", "email_address"
                ),
                "SMS Receivers": _format_receivers(
                    getattr(ag, "sms_receivers", None), "name", "phone_number"
                ),
                "Webhook Receivers": _format_receivers(
                    getattr(ag, "webhook_receivers", None), "name", "service_uri"
                ),
                "Azure App Push": _format_receivers(
                    getattr(ag, "azure_app_push_receivers", None), "name", "email_address"
                ),
                "ITSM Receivers": _format_receivers(
                    getattr(ag, "itsm_receivers", None), "name"
                ),
                "Automation Runbook": _format_receivers(
                    getattr(ag, "automation_runbook_receivers", None), "name"
                ),
                "Azure Function": _format_receivers(
                    getattr(ag, "azure_function_receivers", None), "name", "function_name"
                ),
                "Logic App": _format_receivers(
                    getattr(ag, "logic_app_receivers", None), "name"
                ),
            })
    except Exception as e:
        log.warning("Failed to list action groups: %s", e)

    return rows


def main(subscription_id: str, subscription_name: str) -> None:
    environment = utils.detect_environment()
    if not utils.is_service_available_in_environment("resource", environment):
        sys.exit(0)

    rows = collect_action_groups(subscription_id)

    if not rows:
        print("No action groups found.")
        return

    df = pd.DataFrame(rows)
    filename = utils.create_export_filename(subscription_name, "action-groups", "all")
    utils.save_dataframe_to_excel(df, filename)
    print(f"Exported {len(rows)} action group(s) → {filename}")
    log.info("Export complete: %d action groups", len(rows))


if __name__ == "__main__":
    cfg = utils.get_config()
    sub_id = cfg.get("default_subscription_id", "")
    sub_name = utils.get_subscription_name(sub_id)
    if not sub_id:
        print("ERROR: No subscription configured. Run configure.py first.")
        sys.exit(1)
    main(sub_id, sub_name)
