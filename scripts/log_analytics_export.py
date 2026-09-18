#!/usr/bin/env python3
"""StratusScanCLI-Azure — Log Analytics Workspaces Export"""

import sys
from pathlib import Path
from typing import Any

try:
    import utils
except ImportError:
    sys.path.append(str(Path(__file__).parent.parent))
    import utils

import pandas as pd

utils.setup_logging("log-analytics-export")
utils.log_script_start("log_analytics_export.py", "Log Analytics Workspaces Export")

log = utils.get_logger()


def _format_daily_cap(quota: Any) -> str:
    """dailyQuotaGb: -1 means unlimited (Microsoft.OperationalInsights WorkspaceCapping)."""
    if quota is None:
        return ""
    if quota == -1:
        return "No cap"
    return f"{quota} GB"


def _iso(value: Any) -> str:
    return value.isoformat() if hasattr(value, "isoformat") else utils.s(value)


def _build_row(ws) -> dict:
    ws_id = utils.s(getattr(ws, "id", None))
    cap = getattr(ws, "workspace_capping", None)
    return {
        "Workspace Name": utils.s(getattr(ws, "name", None)),
        "Resource Group": utils.extract_resource_group(ws_id),
        "Location": utils.s(getattr(ws, "location", None)),
        "SKU": utils.s(getattr(getattr(ws, "sku", None), "name", None)),
        "Retention (days)": getattr(ws, "retention_in_days", "") or "",
        "Daily Cap": _format_daily_cap(getattr(cap, "daily_quota_gb", None)),
        "Provisioning State": utils.s(getattr(ws, "provisioning_state", None)),
        "Created Date": _iso(getattr(ws, "created_date", None)),
        "Modified Date": _iso(getattr(ws, "modified_date", None)),
        "Public Network Access (Ingestion)": utils.s(getattr(ws, "public_network_access_for_ingestion", None)),
        "Public Network Access (Query)": utils.s(getattr(ws, "public_network_access_for_query", None)),
    }


def collect_workspaces(subscription_id: str) -> list:
    client = utils.get_azure_client("loganalytics", subscription_id)
    log.info("Listing Log Analytics workspaces for subscription %s", subscription_id)

    return [_build_row(ws) for ws in client.workspaces.list()]


def main(subscription_id: str, subscription_name: str) -> utils.ExportResult:
    environment = utils.detect_environment()
    if not utils.is_service_available_in_environment("resource", environment):
        sys.exit(0)

    rows = collect_workspaces(subscription_id)

    if not rows:
        raise utils.NoResourcesFound("Log Analytics workspaces")

    df = pd.DataFrame(rows)
    filename = utils.create_export_filename(subscription_name, "log-analytics", "all")
    utils.save_dataframe_to_excel(df, filename)
    print(f"Exported {len(rows)} workspace(s) → {filename}")
    log.info("Export complete: %d workspaces", len(rows))
    return utils.ExportResult(rows=len(rows), filename=filename, errors=[])


if __name__ == "__main__":
    import runner

    runner.run_exporter(main, "log-analytics")
