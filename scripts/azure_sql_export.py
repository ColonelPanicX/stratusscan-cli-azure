#!/usr/bin/env python3
"""StratusScanCLI-Azure — Azure SQL Databases Export"""

import sys
from pathlib import Path

try:
    import utils
except ImportError:
    sys.path.append(str(Path(__file__).parent.parent))
    import utils

import pandas as pd

utils.setup_logging("azure-sql-export")
utils.log_script_start("azure_sql_export.py", "Azure SQL Databases Export")

log = utils.get_logger()


def collect_sql_servers_and_dbs(subscription_id: str) -> list:
    client = utils.get_azure_client("sql", subscription_id)
    log.info("Listing all SQL servers in subscription %s", subscription_id)
    servers = list(client.servers.list())
    rows = []
    for server in servers:
        rg = utils.extract_resource_group(server.id)
        try:
            databases = list(client.databases.list_by_server(rg, server.name))
        except Exception as exc:
            log.warning("Could not list databases for server %s: %s", server.name, exc)
            databases = []
        for db in databases:
            if db.name == "master":
                continue
            rows.append({
                "Server Name": server.name,
                "Resource Group": rg,
                "Location": server.location,
                "Database Name": db.name,
                "SKU": db.sku.name if db.sku else "",
                "Edition": db.sku.tier if db.sku else "",
                "Max Size (GB)": (
                    round(db.max_size_bytes / (1024 ** 3), 2)
                    if db.max_size_bytes else ""
                ),
                "Status": db.status or "",
                "Zone Redundant": db.zone_redundant,
                "Collation": db.collation or "",
                "Server FQDN": server.fully_qualified_domain_name or "",
                "TLS Version": server.minimal_tls_version or "",
                "Tags": "; ".join(f"{k}={v}" for k, v in (db.tags or {}).items()),
            })
    return rows


def main(subscription_id: str, subscription_name: str) -> None:
    environment = utils.detect_environment()
    if not utils.is_service_available_in_environment("sql", environment):
        sys.exit(0)

    rows = collect_sql_servers_and_dbs(subscription_id)
    if not rows:
        print("No Azure SQL databases found.")
        return

    df = pd.DataFrame(rows)
    filename = utils.create_export_filename(subscription_name, "azure-sql", "all")
    utils.save_dataframe_to_excel(df, filename, sheet_name="Azure SQL")
    print(f"Exported {len(rows)} database(s) → {filename}")
    log.info("Export complete: %d databases", len(rows))


if __name__ == "__main__":
    sub_id, sub_name = utils.resolve_target_subscription()
    if not sub_id:
        print("ERROR: No subscription configured. Run configure.py first.")
        sys.exit(1)
    main(sub_id, sub_name)
