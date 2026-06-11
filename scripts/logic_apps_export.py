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
    return list(client.workflows.list_by_subscription())


def main(subscription_id: str, subscription_name: str) -> None:
    environment = utils.detect_environment()
    if not utils.is_service_available_in_environment("logic", environment):
        sys.exit(0)

    workflows = collect_workflows(subscription_id)
    if not workflows:
        print("No Logic App workflows found.")
        return

    rows = []
    for wf in workflows:
        tags = wf.tags or {}
        rows.append({
            "Name": wf.name,
            "Resource Group": utils.extract_resource_group(wf.id),
            "Location": wf.location,
            "State": str(wf.state) if wf.state else "",
            "Provisioning State": str(wf.provisioning_state) if wf.provisioning_state else "",
            "Version": wf.version or "",
            "Created": str(wf.created_time) if wf.created_time else "",
            "Changed": str(wf.changed_time) if wf.changed_time else "",
            "Access Endpoint": wf.access_endpoint or "",
            "Tags": "; ".join(f"{k}={v}" for k, v in tags.items()),
        })

    df = pd.DataFrame(rows)
    filename = utils.create_export_filename(subscription_name, "logic-apps", "all")
    utils.save_dataframe_to_excel(df, filename, sheet_name="Logic Apps")
    print(f"Exported {len(rows)} Logic App workflow(s) → {filename}")
    log.info("Export complete: %d workflows", len(rows))


if __name__ == "__main__":
    sub_id, sub_name = utils.resolve_target_subscription()
    if not sub_id:
        print("ERROR: No subscription configured. Run configure.py first.")
        sys.exit(1)
    main(sub_id, sub_name)
