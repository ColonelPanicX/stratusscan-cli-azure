#!/usr/bin/env python3
"""StratusScanCLI-Azure — Cosmos DB Accounts Export"""

import sys
from pathlib import Path

try:
    import utils
except ImportError:
    sys.path.append(str(Path(__file__).parent.parent))
    import utils

import pandas as pd

utils.setup_logging("cosmos-db-export")
utils.log_script_start("cosmos_db_export.py", "Azure Cosmos DB Accounts Export")

log = utils.get_logger()

_CAPABILITY_APIS = (
    ("EnableCassandra", "Cassandra"),
    ("EnableGremlin", "Gremlin"),
    ("EnableTable", "Table"),
    ("EnableMongo", "MongoDB"),
)


def collect_cosmos_accounts(subscription_id: str) -> list:
    client = utils.get_azure_client("cosmosdb", subscription_id)
    log.info("Listing all Cosmos DB accounts in subscription %s", subscription_id)
    return list(client.database_accounts.list())


def _capability_names(acct) -> list:
    return [utils.s(c.name) for c in (acct.capabilities or []) if c.name]


def _api(acct) -> str:
    kind = utils.s(acct.kind)
    capabilities = {c.lower() for c in _capability_names(acct)}
    if kind.lower() == "mongodb":
        return "MongoDB"
    for capability, api in _CAPABILITY_APIS:
        if capability.lower() in capabilities:
            return api
    if kind.lower() == "globaldocumentdb":
        return "NoSQL"
    return kind


def _build_row(acct) -> dict:
    tags = acct.tags or {}
    locations = ", ".join(
        loc.location_name for loc in (acct.locations or []) if loc.location_name
    )
    consistency = acct.consistency_policy
    return {
        "Name": acct.name,
        "Resource Group": utils.extract_resource_group(acct.id),
        "Location": acct.location,
        "Kind": utils.s(acct.kind),
        "API": _api(acct),
        "Consistency Level": utils.s(consistency.default_consistency_level) if consistency else "",
        "Document Endpoint": acct.document_endpoint or "",
        "Geo-replication Regions": locations,
        "Automatic Failover": "" if acct.enable_automatic_failover is None else acct.enable_automatic_failover,
        "Multiple Write Locations": (
            "" if acct.enable_multiple_write_locations is None else acct.enable_multiple_write_locations
        ),
        "Public Network Access": utils.s(acct.public_network_access),
        "Provisioning State": utils.s(acct.provisioning_state),
        "Tags": "; ".join(f"{k}={v}" for k, v in tags.items()),
        "Capabilities": ", ".join(_capability_names(acct)),
        "Disable Local Auth": "" if acct.disable_local_auth is None else acct.disable_local_auth,
        "Minimal TLS Version": utils.s(acct.minimal_tls_version),
    }


def main(subscription_id: str, subscription_name: str) -> None:
    environment = utils.detect_environment()
    if not utils.is_service_available_in_environment("cosmosdb", environment):
        sys.exit(0)

    accounts = collect_cosmos_accounts(subscription_id)
    if not accounts:
        print("No Cosmos DB accounts found.")
        return

    rows = [_build_row(acct) for acct in accounts]

    df = pd.DataFrame(rows)
    filename = utils.create_export_filename(subscription_name, "cosmos-db", "all")
    utils.save_dataframe_to_excel(df, filename, sheet_name="Cosmos DB")
    print(f"Exported {len(rows)} Cosmos DB account(s) → {filename}")
    log.info("Export complete: %d Cosmos DB accounts", len(rows))


if __name__ == "__main__":
    sub_id, sub_name = utils.resolve_target_subscription()
    if not sub_id:
        print("ERROR: No subscription configured. Run configure.py first.")
        sys.exit(1)
    main(sub_id, sub_name)
