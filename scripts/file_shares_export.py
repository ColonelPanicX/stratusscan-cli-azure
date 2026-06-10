#!/usr/bin/env python3
"""StratusScanCLI-Azure — File Shares Inventory Export"""

import sys
from pathlib import Path

try:
    import utils
except ImportError:
    sys.path.append(str(Path(__file__).parent.parent))
    import utils

import pandas as pd

utils.setup_logging("file-shares-export")
utils.log_script_start("file_shares_export.py", "File Shares Inventory Export")

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
    log.info("Listing file shares across storage accounts in %s", subscription_id)

    rows = []
    for rg, account in _iter_accounts(client):
        try:
            for s in client.file_shares.list(rg, account):
                enabled_protocols = getattr(s, "enabled_protocols", "") or ""
                rows.append({
                    "Storage Account": account,
                    "Share Name": s.name,
                    "Resource Group": rg,
                    "Access Tier": str(getattr(s, "access_tier", "")) if getattr(s, "access_tier", None) else "",
                    "Quota GB": getattr(s, "share_quota", "") if getattr(s, "share_quota", None) is not None else "",
                    "Used Capacity (bytes)": getattr(s, "share_usage_bytes", "") if getattr(s, "share_usage_bytes", None) is not None else "",
                    "Enabled Protocols": str(enabled_protocols),
                    "Provisioning State": str(getattr(s, "provisioning_state", "")) if getattr(s, "provisioning_state", None) else "",
                })
        except Exception as e:
            log.warning("Failed to list file shares for account %s: %s", account, e)

    if not rows:
        print("No file shares found.")
        return

    df = pd.DataFrame(rows)
    filename = utils.create_export_filename(subscription_name, "file-shares", "all")
    utils.save_dataframe_to_excel(df, filename, sheet_name="File Shares")
    print(f"Exported {len(rows)} file share(s) → {filename}")
    log.info("Export complete: %d file shares", len(rows))


if __name__ == "__main__":
    cfg = utils.get_config()
    sub_id = cfg.get("default_subscription_id", "")
    sub_name = utils.get_subscription_name(sub_id)
    if not sub_id:
        print("ERROR: No subscription configured. Run configure.py first.")
        sys.exit(1)
    main(sub_id, sub_name)
