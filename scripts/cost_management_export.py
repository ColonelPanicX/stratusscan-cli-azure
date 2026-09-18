#!/usr/bin/env python3
"""StratusScanCLI-Azure — Cost Management Export (month-to-date actual cost)"""

import sys
from pathlib import Path

try:
    import utils
except ImportError:
    sys.path.append(str(Path(__file__).parent.parent))
    import utils

import pandas as pd

utils.setup_logging("cost-management-export")
utils.log_script_start("cost_management_export.py", "Azure Cost Management Export")

log = utils.get_logger()

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
    client = utils.get_azure_client("costmanagement")
    scope = f"/subscriptions/{subscription_id}"
    log.info("Querying month-to-date cost for subscription %s", subscription_id)

    result = client.query.usage(scope=scope, parameters=_QUERY)
    if result is None:
        return []
    columns = [getattr(c, "name", "") for c in (result.columns or [])]
    return [dict(zip(columns, raw)) for raw in result.rows or []]


def main(subscription_id: str, subscription_name: str) -> utils.ExportResult:
    environment = utils.detect_environment()
    if not utils.is_service_available_in_environment("costmanagement", environment):
        sys.exit(0)

    rows = collect_costs(subscription_id)

    if not rows:
        raise utils.NoResourcesFound("cost data")

    df = pd.DataFrame(rows)
    filename = utils.create_export_filename(subscription_name, "cost-management", "mtd")
    utils.save_dataframe_to_excel(df, filename)
    print(f"Exported {len(rows)} cost row(s) → {filename}")
    log.info("Export complete: %d cost rows", len(rows))
    return utils.ExportResult(rows=len(rows), filename=filename, errors=[])


if __name__ == "__main__":
    import runner

    runner.run_exporter(main, "cost-management")
