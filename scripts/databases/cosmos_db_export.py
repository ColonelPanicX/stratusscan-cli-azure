#!/usr/bin/env python3
"""StratusScanCLI-Azure — Cosmos DB Accounts Export"""

import sys
from pathlib import Path

try:
    import utils
except ImportError:
    sys.path.append(str(Path(__file__).parent.parent.parent))
    import utils

import pandas as pd

utils.setup_logging("cosmos-db-export")
utils.log_script_start("cosmos_db_export.py", "Azure Cosmos DB Accounts Export")

log = utils.get_logger()


def collect_cosmos_accounts(subscription_id: str) -> list:
    client = utils.get_azure_client("cosmosdb", subscription_id)
    log.info("Listing all Cosmos DB accounts in subscription %s", subscription_id)
    return list(client.database_accounts.list())


def main(subscription_id: str, subscription_name: str) -> None:
    environment = utils.detect_environment()
    if not utils.is_service_available_in_environment("cosmosdb", environment):
        sys.exit(0)

    accounts = collect_cosmos_accounts(subscription_id)
    if not accounts:
        print("No Cosmos DB accounts found.")
        return

    rows = []
    for acct in accounts:
        rg = utils.extract_resource_group(acct.id)
        tags = acct.tags or {}
        locations = ", ".join(
            loc.location_name for loc in (acct.locations or []) if loc.location_name
        )
        rows.append({
            "Name": acct.name,
            "Resource Group": rg,
            "Location": acct.location,
            "Kind": str(acct.kind) if acct.kind else "",
            "API": str(acct.kind) if acct.kind else "",
            "Consistency Level": (
                str(acct.consistency_policy.default_consistency_level)
                if acct.consistency_policy else ""
            ),
            "Document Endpoint": acct.document_endpoint or "",
            "Geo-replication Regions": locations,
            "Automatic Failover": acct.enable_automatic_failover,
            "Multiple Write Locations": acct.enable_multiple_write_locations,
            "Public Network Access": str(acct.public_network_access) if acct.public_network_access else "",
            "Provisioning State": acct.provisioning_state or "",
            "Tags": "; ".join(f"{k}={v}" for k, v in tags.items()),
        })

    df = pd.DataFrame(rows)
    filename = utils.create_export_filename(subscription_name, "cosmos-db", "all")
    utils.save_dataframe_to_excel(df, filename, sheet_name="Cosmos DB")
    print(f"Exported {len(rows)} Cosmos DB account(s) → {filename}")
    log.info("Export complete: %d Cosmos DB accounts", len(rows))


if __name__ == "__main__":
    cfg = utils.get_config()
    sub_id = cfg.get("default_subscription_id", "")
    sub_name = utils.get_subscription_name(sub_id)
    if not sub_id:
        print("ERROR: No subscription configured. Run configure.py first.")
        sys.exit(1)
    main(sub_id, sub_name)
