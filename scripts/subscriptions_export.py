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

log = utils.get_logger()


def collect_subscriptions() -> list:
    log.info("Listing all accessible subscriptions")
    return utils.list_subscriptions()


def main(subscription_id: str, subscription_name: str) -> utils.ExportResult:
    subs = collect_subscriptions()
    if not subs:
        log.warning("No subscriptions found or accessible")
        raise utils.NoResourcesFound("subscriptions")

    rows = []
    for sub in subs:
        rows.append({
            "Subscription ID": sub.get("id", ""),
            "Subscription Name": sub.get("name", ""),
            "State": sub.get("state", ""),
            "Tenant ID": sub.get("tenant_id", ""),
        })

    df = pd.DataFrame(rows)
    filename = utils.create_export_filename("TENANT", "subscriptions", "all")
    utils.save_dataframe_to_excel(df, filename, sheet_name="Subscriptions")
    print(f"Exported {len(rows)} subscription(s) → {filename}")
    log.info("Export complete: %d subscriptions", len(rows))
    return utils.ExportResult(rows=len(rows), filename=filename, errors=[])


if __name__ == "__main__":
    import runner

    runner.run_exporter(main, "subscriptions")
