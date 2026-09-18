#!/usr/bin/env python3
"""StratusScanCLI-Azure — Logic Apps (Workflows) Export"""

import sys
from pathlib import Path

try:
    import utils
except ImportError:
    sys.path.append(str(Path(__file__).parent.parent))
    import utils

import pandas as pd

utils.setup_logging("logic-apps-export")
utils.log_script_start("logic_apps_export.py", "Logic Apps (Workflows) Export")

log = utils.get_logger()


def collect_workflows(subscription_id: str) -> list:
    client = utils.get_azure_client("logic", subscription_id)
    log.info("Listing Logic App workflows in subscription %s", subscription_id)
    return list(utils.list_subscription_wide(client.workflows, "list_by_subscription", "list"))


def main(subscription_id: str, subscription_name: str) -> utils.ExportResult:
    environment = utils.detect_environment()
    if not utils.is_service_available_in_environment("logic", environment):
        sys.exit(0)

    workflows = collect_workflows(subscription_id)
    if not workflows:
        raise utils.NoResourcesFound("Logic App workflows")

    errors: list = []
    rows = []
    for wf in workflows:
        tags = wf.tags or {}
        rows.append({
            "Name": wf.name,
            "Resource Group": utils.extract_resource_group(wf.id),
            "Location": wf.location,
            "State": utils.s(wf.state),
            "Provisioning State": utils.s(wf.provisioning_state),
            "Version": wf.version or "",
            "Created": utils.s(wf.created_time),
            "Changed": utils.s(wf.changed_time),
            "Access Endpoint": wf.access_endpoint or "",
            "Tags": "; ".join(f"{k}={v}" for k, v in tags.items()),
        })

    df = pd.DataFrame(rows)
    filename = utils.create_export_filename(subscription_name, "logic-apps", "all")
    utils.save_dataframe_to_excel(df, filename, sheet_name="Logic Apps", errors=errors)
    print(f"Exported {len(rows)} Logic App workflow(s) → {filename}")
    log.info("Export complete: %d workflows", len(rows))
    return utils.ExportResult(rows=len(rows), filename=filename, errors=errors)


if __name__ == "__main__":
    import runner

    runner.run_exporter(main, "logic-apps")
