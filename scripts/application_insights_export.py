#!/usr/bin/env python3
"""StratusScanCLI-Azure — Application Insights Export

Instrumentation keys and connection strings are deliberately NOT exported —
this is an inventory/audit tool, not a secrets dump.
"""

import sys
from pathlib import Path

try:
    import utils
except ImportError:
    sys.path.append(str(Path(__file__).parent.parent))
    import utils

import pandas as pd

log = utils.get_logger()


def collect_components(subscription_id: str) -> list:
    client = utils.get_azure_client("applicationinsights", subscription_id)
    log.info("Listing Application Insights components in subscription %s", subscription_id)
    return list(client.components.list())


def main(subscription_id: str, subscription_name: str) -> utils.ExportResult:
    environment = utils.detect_environment()
    if not utils.is_service_available_in_environment("applicationinsights", environment):
        sys.exit(0)

    components = collect_components(subscription_id)
    if not components:
        raise utils.NoResourcesFound("Application Insights components")

    rows = []
    for comp in components:
        tags = comp.tags or {}
        workspace = getattr(comp, "workspace_resource_id", "") or ""
        rows.append({
            "Name": comp.name,
            "Resource Group": utils.extract_resource_group(comp.id),
            "Location": comp.location,
            "Application Type": getattr(comp, "application_type", "") or "",
            "Kind": getattr(comp, "kind", "") or "",
            "App ID": getattr(comp, "app_id", "") or "",
            "Workspace-Based": "Yes" if workspace else "No (classic)",
            "Workspace": workspace.split("/")[-1] if workspace else "",
            "Retention (days)": getattr(comp, "retention_in_days", "") if getattr(comp, "retention_in_days", None) is not None else "",
            "Ingestion Mode": utils.s(getattr(comp, "ingestion_mode", None)),
            "Public Network Access (Ingestion)": utils.s(getattr(comp, "public_network_access_for_ingestion", None)),
            "Provisioning State": getattr(comp, "provisioning_state", "") or "",
            "Tags": "; ".join(f"{k}={v}" for k, v in tags.items()),
        })

    df = pd.DataFrame(rows)
    filename = utils.create_export_filename(subscription_name, "application-insights", "all")
    utils.save_dataframe_to_excel(df, filename, sheet_name="Application Insights")
    print(f"Exported {len(rows)} Application Insights component(s) → {filename}")
    log.info("Export complete: %d components", len(rows))
    return utils.ExportResult(rows=len(rows), filename=filename, errors=[])


if __name__ == "__main__":
    import runner

    runner.run_exporter(main, "application-insights")
