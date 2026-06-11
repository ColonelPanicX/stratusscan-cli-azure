#!/usr/bin/env python3
"""StratusScanCLI-Azure — Network Watchers Export"""

import sys
from pathlib import Path

try:
    import utils
except ImportError:
    sys.path.append(str(Path(__file__).parent.parent))
    import utils

import pandas as pd

utils.setup_logging("network-watchers-export")
utils.log_script_start("network_watchers_export.py", "Network Watchers Export")

log = utils.get_logger()


def collect_watchers(subscription_id: str) -> list:
    client = utils.get_azure_client("network", subscription_id)
    log.info("Listing all network watchers in subscription %s", subscription_id)
    return list(client.network_watchers.list_all())


def main(subscription_id: str, subscription_name: str) -> None:
    environment = utils.detect_environment()
    if not utils.is_service_available_in_environment("network", environment):
        sys.exit(0)

    watchers = collect_watchers(subscription_id)
    if not watchers:
        print("No network watchers found.")
        return

    rows = []
    for w in watchers:
        rg = w.id.split("/resourceGroups/")[1].split("/")[0] if w.id else ""
        tags = w.tags or {}
        rows.append({
            "Name": w.name,
            "Resource Group": rg,
            "Location": w.location,
            "Provisioning State": w.provisioning_state or "",
            "Tags": "; ".join(f"{k}={v}" for k, v in tags.items()),
        })

    df = pd.DataFrame(rows)
    filename = utils.create_export_filename(subscription_name, "network-watchers", "all")
    utils.save_dataframe_to_excel(df, filename, sheet_name="Network Watchers")
    print(f"Exported {len(rows)} network watcher(s) → {filename}")
    log.info("Export complete: %d watchers", len(rows))


if __name__ == "__main__":
    sub_id, sub_name = utils.resolve_target_subscription()
    if not sub_id:
        print("ERROR: No subscription configured. Run configure.py first.")
        sys.exit(1)
    main(sub_id, sub_name)
