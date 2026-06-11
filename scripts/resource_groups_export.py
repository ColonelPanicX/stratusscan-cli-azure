#!/usr/bin/env python3
"""StratusScanCLI-Azure — Resource Groups Export"""

import sys
from pathlib import Path

try:
    import utils
except ImportError:
    sys.path.append(str(Path(__file__).parent.parent))
    import utils

import pandas as pd

utils.setup_logging("resource-groups-export")
utils.log_script_start("resource_groups_export.py", "Azure Resource Groups Export")

log = utils.get_logger()


def collect_resource_groups(subscription_id: str) -> list:
    client = utils.get_azure_client("resource", subscription_id)
    log.info("Listing resource groups for subscription %s", subscription_id)
    return list(client.resource_groups.list())


def main(subscription_id: str, subscription_name: str) -> None:
    environment = utils.detect_environment()
    if not utils.is_service_available_in_environment("resource", environment):
        sys.exit(0)

    rgs = collect_resource_groups(subscription_id)
    if not rgs:
        print("No resource groups found.")
        return

    rows = []
    for rg in rgs:
        tags = rg.tags or {}
        rows.append({
            "Name": rg.name,
            "Location": rg.location,
            "Provisioning State": rg.properties.provisioning_state if rg.properties else "",
            "Tags": "; ".join(f"{k}={v}" for k, v in tags.items()),
        })

    df = pd.DataFrame(rows)
    filename = utils.create_export_filename(subscription_name, "resource-groups", "all")
    utils.save_dataframe_to_excel(df, filename, sheet_name="Resource Groups")
    print(f"Exported {len(rows)} resource group(s) → {filename}")
    log.info("Export complete: %d resource groups", len(rows))


if __name__ == "__main__":
    sub_id, sub_name = utils.resolve_target_subscription()
    if not sub_id:
        print("ERROR: No subscription configured. Run configure.py first.")
        sys.exit(1)
    main(sub_id, sub_name)
