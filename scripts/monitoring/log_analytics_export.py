#!/usr/bin/env python3
"""StratusScanCLI-Azure — Log Analytics Workspaces Export"""

import sys
from pathlib import Path

try:
    import utils
except ImportError:
    sys.path.append(str(Path(__file__).parent.parent.parent))
    import utils

import pandas as pd

utils.setup_logging("log-analytics-export")
utils.log_script_start("log_analytics_export.py", "Log Analytics Workspaces Export")

log = utils.get_logger()


def collect_workspaces(subscription_id: str) -> list:
    client = utils.get_azure_client("loganalytics", subscription_id)
    log.info("Listing Log Analytics workspaces for subscription %s", subscription_id)

    rows = []
    try:
        for ws in client.workspaces.list():
            rg = ""
            ws_id = getattr(ws, "id", "") or ""
            if "/resourceGroups/" in ws_id:
                rg = ws_id.split("/resourceGroups/")[1].split("/")[0]

            sku_name = ""
            sku = getattr(ws, "sku", None)
            if sku:
                sku_name = getattr(sku, "name", "") or ""

            daily_cap = ""
            cap = getattr(ws, "workspace_capping", None)
            if cap:
                quota = getattr(cap, "daily_quota_gb", None)
                if quota is not None and quota >= 0:
                    daily_cap = f"{quota} GB"

            created = getattr(ws, "created_date", "") or ""
            if hasattr(created, "isoformat"):
                created = created.isoformat()

            modified = getattr(ws, "modified_date", "") or ""
            if hasattr(modified, "isoformat"):
                modified = modified.isoformat()

            rows.append({
                "Workspace Name": getattr(ws, "name", "") or "",
                "Resource Group": rg,
                "Location": getattr(ws, "location", "") or "",
                "SKU": sku_name,
                "Retention (days)": getattr(ws, "retention_in_days", "") or "",
                "Daily Cap": daily_cap,
                "Provisioning State": getattr(ws, "provisioning_state", "") or "",
                "Created Date": created,
                "Modified Date": modified,
            })
    except Exception as e:
        log.warning("Failed to list Log Analytics workspaces: %s", e)

    return rows


def main(subscription_id: str, subscription_name: str) -> None:
    environment = utils.detect_environment()
    if not utils.is_service_available_in_environment("resource", environment):
        sys.exit(0)

    rows = collect_workspaces(subscription_id)

    if not rows:
        print("No Log Analytics workspaces found.")
        return

    df = pd.DataFrame(rows)
    filename = utils.create_export_filename(subscription_name, "log-analytics", "all")
    utils.save_dataframe_to_excel(df, filename)
    print(f"Exported {len(rows)} workspace(s) → {filename}")
    log.info("Export complete: %d workspaces", len(rows))


if __name__ == "__main__":
    cfg = utils.get_config()
    sub_id = cfg.get("default_subscription_id", "")
    sub_name = utils.get_subscription_name(sub_id)
    if not sub_id:
        print("ERROR: No subscription configured. Run configure.py first.")
        sys.exit(1)
    main(sub_id, sub_name)
