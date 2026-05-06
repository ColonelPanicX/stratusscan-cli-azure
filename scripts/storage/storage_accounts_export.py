#!/usr/bin/env python3
"""StratusScanCLI-Azure — Storage Accounts Export"""

import sys
from pathlib import Path

try:
    import utils
except ImportError:
    sys.path.append(str(Path(__file__).parent.parent.parent))
    import utils

import pandas as pd

utils.setup_logging("storage-accounts-export")
utils.log_script_start("storage_accounts_export.py", "Azure Storage Accounts Export")

log = utils.get_logger()


def collect_storage_accounts(subscription_id: str) -> list:
    client = utils.get_azure_client("storage", subscription_id)
    log.info("Listing all storage accounts in subscription %s", subscription_id)
    return list(client.storage_accounts.list())


def main(subscription_id: str, subscription_name: str) -> None:
    environment = utils.detect_environment()
    if not utils.is_service_available_in_environment("storage", environment):
        sys.exit(0)

    accounts = collect_storage_accounts(subscription_id)
    if not accounts:
        print("No storage accounts found.")
        return

    rows = []
    for acct in accounts:
        rg = acct.id.split("/resourceGroups/")[1].split("/")[0] if acct.id else ""
        tags = acct.tags or {}
        rows.append({
            "Name": acct.name,
            "Resource Group": rg,
            "Location": acct.location,
            "SKU": acct.sku.name if acct.sku else "",
            "Kind": str(acct.kind) if acct.kind else "",
            "Access Tier": str(acct.access_tier) if acct.access_tier else "",
            "HTTPS Only": acct.enable_https_traffic_only,
            "Replication": acct.sku.tier if acct.sku else "",
            "Public Network Access": str(acct.public_network_access) if acct.public_network_access else "Enabled",
            "Minimum TLS Version": str(acct.minimum_tls_version) if acct.minimum_tls_version else "",
            "Blob Soft Delete": (
                acct.blob_restore_status is not None
                if hasattr(acct, "blob_restore_status") else ""
            ),
            "Allow Blob Public Access": getattr(acct, "allow_blob_public_access", ""),
            "Provisioning State": str(acct.provisioning_state) if acct.provisioning_state else "",
            "Tags": "; ".join(f"{k}={v}" for k, v in tags.items()),
        })

    df = pd.DataFrame(rows)
    filename = utils.create_export_filename(subscription_name, "storage-accounts", "all")
    utils.save_dataframe_to_excel(df, filename, sheet_name="Storage Accounts")
    print(f"Exported {len(rows)} storage account(s) → {filename}")
    log.info("Export complete: %d storage accounts", len(rows))


if __name__ == "__main__":
    cfg = utils.get_config()
    sub_id = cfg.get("default_subscription_id", "")
    sub_name = utils.get_subscription_name(sub_id)
    if not sub_id:
        print("ERROR: No subscription configured. Run configure.py first.")
        sys.exit(1)
    main(sub_id, sub_name)
