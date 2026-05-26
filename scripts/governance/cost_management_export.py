#!/usr/bin/env python3
"""StratusScanCLI-Azure — Cost Management Export (month-to-date actual cost)"""

import sys
from pathlib import Path

try:
    import utils
except ImportError:
    sys.path.append(str(Path(__file__).parent.parent.parent))
    import utils

import pandas as pd

utils.setup_logging("cost-management-export")
utils.log_script_start("cost_management_export.py", "Azure Cost Management Export")

log = utils.get_logger()

# Actual cost, month-to-date, grouped by resource group and service.
# Passed as a plain dict so it deserializes across azure-mgmt-costmanagement versions.
_QUERY = {
    "type": "ActualCost",
    "timeframe": "MonthToDate",
    "dataset": {
        "granularity": "None",
        "aggregation": {"totalCost": {"name": "Cost", "function": "Sum"}},
        "grouping": [
            {"type": "Dimension", "name": "ResourceGroupName"},
            {"type": "Dimension", "name": "ServiceName"},
        ],
    },
}


def collect_costs(subscription_id: str) -> list:
    client = utils.get_azure_client("costmanagement", subscription_id)
    scope = f"/subscriptions/{subscription_id}"
    log.info("Querying month-to-date cost for subscription %s", subscription_id)

    rows = []
    try:
        result = client.query.usage(scope=scope, parameters=_QUERY)
        columns = [getattr(c, "name", "") for c in (result.columns or [])]
        for raw in (result.rows or []):
            rows.append(dict(zip(columns, raw)))
    except Exception as e:
        log.warning("Failed to query Cost Management: %s", e)

    return rows


def main(subscription_id: str, subscription_name: str) -> None:
    environment = utils.detect_environment()
    if not utils.is_service_available_in_environment("resource", environment):
        sys.exit(0)

    rows = collect_costs(subscription_id)

    if not rows:
        print("No cost data found for the current billing period.")
        return

    df = pd.DataFrame(rows)
    filename = utils.create_export_filename(subscription_name, "cost-management", "mtd")
    utils.save_dataframe_to_excel(df, filename)
    print(f"Exported {len(rows)} cost row(s) → {filename}")
    log.info("Export complete: %d cost rows", len(rows))


if __name__ == "__main__":
    cfg = utils.get_config()
    sub_id = cfg.get("default_subscription_id", "")
    sub_name = utils.get_subscription_name(sub_id)
    if not sub_id:
        print("ERROR: No subscription configured. Run configure.py first.")
        sys.exit(1)
    main(sub_id, sub_name)
