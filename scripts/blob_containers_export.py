#!/usr/bin/env python3
"""StratusScanCLI-Azure — Blob Containers Inventory Export"""

import sys
from pathlib import Path

try:
    import utils
except ImportError:
    sys.path.append(str(Path(__file__).parent.parent))
    import utils

import pandas as pd

utils.setup_logging("blob-containers-export")
utils.log_script_start("blob_containers_export.py", "Blob Containers Inventory Export")

log = utils.get_logger()


def _iter_accounts(client):
    for acct in client.storage_accounts.list():
        rg = acct.id.split("/resourceGroups/")[1].split("/")[0] if acct.id else ""
        yield rg, acct.name


def main(subscription_id: str, subscription_name: str) -> None:
    environment = utils.detect_environment()
    if not utils.is_service_available_in_environment("storage", environment):
        sys.exit(0)

    client = utils.get_azure_client("storage", subscription_id)
    log.info("Listing blob containers across storage accounts in %s", subscription_id)

    rows = []
    for rg, account in _iter_accounts(client):
        try:
            for c in client.blob_containers.list(rg, account):
                metadata = getattr(c, "metadata", None) or {}
                rows.append({
                    "Storage Account": account,
                    "Container Name": c.name,
                    "Resource Group": rg,
                    "Public Access Level": str(getattr(c, "public_access", "")) if getattr(c, "public_access", None) else "None",
                    "Lease State": str(getattr(c, "lease_state", "")) if getattr(c, "lease_state", None) else "",
                    "Has Immutability Policy": "Yes" if getattr(c, "has_immutability_policy", False) else "No",
                    "Has Legal Hold": "Yes" if getattr(c, "has_legal_hold", False) else "No",
                    "Default Encryption Scope": getattr(c, "default_encryption_scope", "") or "",
                    "Last Modified": str(getattr(c, "last_modified_time", "")) if getattr(c, "last_modified_time", None) else "",
                    "Metadata": "; ".join(f"{k}={v}" for k, v in metadata.items()),
                })
        except Exception as e:
            log.warning("Failed to list containers for account %s: %s", account, e)

    if not rows:
        print("No blob containers found.")
        return

    df = pd.DataFrame(rows)
    filename = utils.create_export_filename(subscription_name, "blob-containers", "all")
    utils.save_dataframe_to_excel(df, filename, sheet_name="Blob Containers")
    print(f"Exported {len(rows)} blob container(s) → {filename}")
    log.info("Export complete: %d containers", len(rows))


if __name__ == "__main__":
    sub_id, sub_name = utils.resolve_target_subscription()
    if not sub_id:
        print("ERROR: No subscription configured. Run configure.py first.")
        sys.exit(1)
    main(sub_id, sub_name)
