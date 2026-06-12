#!/usr/bin/env python3
"""StratusScanCLI-Azure — PostgreSQL Flexible Server Export"""

import sys
from pathlib import Path

try:
    import utils
except ImportError:
    sys.path.append(str(Path(__file__).parent.parent))
    import utils

import pandas as pd

utils.setup_logging("postgresql-flexible-export")
utils.log_script_start("postgresql_flexible_export.py", "PostgreSQL Flexible Server Export")

log = utils.get_logger()


def collect_servers(subscription_id: str) -> list:
    client = utils.get_azure_client("postgresql", subscription_id)
    log.info("Listing PostgreSQL flexible servers in subscription %s", subscription_id)
    if hasattr(client.servers, "list"):
        return list(client.servers.list())

    resource = utils.get_azure_client("resource", subscription_id)
    servers = []
    for rg in resource.resource_groups.list():
        try:
            servers.extend(client.servers.list_by_resource_group(rg.name))
        except Exception as exc:
            log.warning("Failed to list PostgreSQL flexible servers in %s: %s", rg.name, exc)
    return servers


def main(subscription_id: str, subscription_name: str) -> None:
    environment = utils.detect_environment()
    if not utils.is_service_available_in_environment("postgresql", environment):
        sys.exit(0)

    servers = collect_servers(subscription_id)
    if not servers:
        print("No PostgreSQL flexible servers found.")
        return

    rows = []
    for srv in servers:
        sku = srv.sku
        storage = srv.storage
        backup = srv.backup
        ha = srv.high_availability
        network = srv.network
        tags = srv.tags or {}
        rows.append({
            "Name": srv.name,
            "Resource Group": utils.extract_resource_group(srv.id),
            "Location": srv.location,
            "Version": srv.version or "",
            "SKU": sku.name if sku else "",
            "Tier": sku.tier if sku else "",
            "Admin Login": srv.administrator_login or "",
            "Storage GB": getattr(storage, "storage_size_gb", "") if storage else "",
            "Backup Retention Days": getattr(backup, "backup_retention_days", "") if backup else "",
            "Geo-Redundant Backup": str(getattr(backup, "geo_redundant_backup", "")) if backup else "",
            "HA Mode": str(getattr(ha, "mode", "")) if ha else "",
            "State": srv.state or "",
            "FQDN": srv.fully_qualified_domain_name or "",
            "Public Network Access": str(getattr(network, "public_network_access", "")) if network else "",
            "Tags": "; ".join(f"{k}={v}" for k, v in tags.items()),
        })

    df = pd.DataFrame(rows)
    filename = utils.create_export_filename(subscription_name, "postgresql-flexible", "all")
    utils.save_dataframe_to_excel(df, filename, sheet_name="PostgreSQL Flexible")
    print(f"Exported {len(rows)} PostgreSQL flexible server(s) → {filename}")
    log.info("Export complete: %d servers", len(rows))


if __name__ == "__main__":
    sub_id, sub_name = utils.resolve_target_subscription()
    if not sub_id:
        print("ERROR: No subscription configured. Run configure.py first.")
        sys.exit(1)
    main(sub_id, sub_name)
