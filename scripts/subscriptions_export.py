#!/usr/bin/env python3
"""StratusScanCLI-Azure — Subscriptions Export"""

import sys
from pathlib import Path

try:
    import utils
except ImportError:
    sys.path.append(str(Path(__file__).parent.parent))
    import utils

import pandas as pd

utils.setup_logging("subscriptions-export")
utils.log_script_start("subscriptions_export.py", "Azure Subscriptions Export")

log = utils.get_logger()


def collect_subscriptions() -> list:
    log.info("Listing all accessible subscriptions")
    return utils.list_subscriptions()


def main() -> None:
    subs = collect_subscriptions()
    if not subs:
        log.warning("No subscriptions found or accessible")
        print("No subscriptions found.")
        return

    rows = []
    for sub in subs:
        rows.append({
            "Subscription ID": sub.get("id", ""),
            "Subscription Name": sub.get("name", ""),
            "State": sub.get("state", ""),
            "Tenant ID": sub.get("tenant_id", ""),
        })

    df = pd.DataFrame(rows)
    timestamp = utils.get_current_timestamp()
    filename = utils.create_export_filename("TENANT", "subscriptions", "all")
    utils.save_dataframe_to_excel(df, filename, sheet_name="Subscriptions")
    print(f"Exported {len(rows)} subscription(s) → {filename}")
    log.info("Export complete: %d subscriptions", len(rows))


if __name__ == "__main__":
    main()
