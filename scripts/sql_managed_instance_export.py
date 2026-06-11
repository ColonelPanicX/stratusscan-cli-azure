#!/usr/bin/env python3
"""StratusScanCLI-Azure — SQL Managed Instance Export"""

import sys
from pathlib import Path

try:
    import utils
except ImportError:
    sys.path.append(str(Path(__file__).parent.parent))
    import utils

import pandas as pd

utils.setup_logging("sql-managed-instance-export")
utils.log_script_start("sql_managed_instance_export.py", "SQL Managed Instance Export")

log = utils.get_logger()


def collect_instances(subscription_id: str) -> list:
    client = utils.get_azure_client("sql", subscription_id)
    log.info("Listing all SQL managed instances in subscription %s", subscription_id)
    return list(client.managed_instances.list())


def main(subscription_id: str, subscription_name: str) -> None:
    environment = utils.detect_environment()
    if not utils.is_service_available_in_environment("sql", environment):
        sys.exit(0)

    instances = collect_instances(subscription_id)
    if not instances:
        print("No SQL managed instances found.")
        return

    rows = []
    for mi in instances:
        rg = mi.id.split("/resourceGroups/")[1].split("/")[0] if mi.id else ""
        subnet_id = getattr(mi, "subnet_id", "") or ""
        tags = mi.tags or {}
        rows.append({
            "Name": mi.name,
            "Resource Group": rg,
            "Location": mi.location,
            "SKU Name": mi.sku.name if mi.sku else "",
            "SKU Tier": mi.sku.tier if mi.sku else "",
            "vCores": getattr(mi, "v_cores", "") if getattr(mi, "v_cores", None) is not None else "",
            "Storage Size GB": getattr(mi, "storage_size_in_gb", "") if getattr(mi, "storage_size_in_gb", None) is not None else "",
            "License Type": getattr(mi, "license_type", "") or "",
            "Subnet": subnet_id.split("/")[-1] if subnet_id else "",
            "Public Endpoint Enabled": "Yes" if getattr(mi, "public_data_endpoint_enabled", False) else "No",
            "Proxy Override": getattr(mi, "proxy_override", "") or "",
            "Minimal TLS Version": getattr(mi, "minimal_tls_version", "") or "",
            "Admin Login": getattr(mi, "administrator_login", "") or "",
            "State": getattr(mi, "state", "") or "",
            "FQDN": getattr(mi, "fully_qualified_domain_name", "") or "",
            "Tags": "; ".join(f"{k}={v}" for k, v in tags.items()),
        })

    df = pd.DataFrame(rows)
    filename = utils.create_export_filename(subscription_name, "sql-managed-instance", "all")
    utils.save_dataframe_to_excel(df, filename, sheet_name="SQL Managed Instances")
    print(f"Exported {len(rows)} SQL managed instance(s) → {filename}")
    log.info("Export complete: %d managed instances", len(rows))


if __name__ == "__main__":
    sub_id, sub_name = utils.resolve_target_subscription()
    if not sub_id:
        print("ERROR: No subscription configured. Run configure.py first.")
        sys.exit(1)
    main(sub_id, sub_name)
