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
from azure.core.exceptions import HttpResponseError

utils.setup_logging("file-shares-export")
utils.log_script_start("file_shares_export.py", "File Shares Inventory Export")

log = utils.get_logger()


def _iter_accounts(client):
    for acct in client.storage_accounts.list():
        yield utils.extract_resource_group(acct.id), acct.name


def _build_row(share, account: str, rg: str) -> dict:
    return {
        "Storage Account": account,
        "Share Name": share.name,
        "Resource Group": rg,
        "Access Tier": utils.s(share.access_tier),
        "Quota GB": share.share_quota if share.share_quota is not None else "",
        "Enabled Protocols": utils.s(share.enabled_protocols),
        "Root Squash": utils.s(share.root_squash),
        "Lease State": utils.s(share.lease_state),
        "Lease Status": utils.s(share.lease_status),
    }


def main(subscription_id: str, subscription_name: str) -> None:
    environment = utils.detect_environment()
    if not utils.is_service_available_in_environment("storage", environment):
        sys.exit(0)

    client = utils.get_azure_client("storage", subscription_id)
    log.info("Listing file shares across storage accounts in %s", subscription_id)

    rows = []
    unsupported_accounts = 0
    for rg, account in _iter_accounts(client):
        try:
            for share in client.file_shares.list(rg, account):
                rows.append(_build_row(share, account, rg))
        except HttpResponseError as e:
            if getattr(e, "error", None) and getattr(e.error, "code", "") == "FeatureNotSupportedForAccount":
                unsupported_accounts += 1
                log.info("Skipping file shares for unsupported account %s", account)
                continue
            log.warning("Failed to list file shares for account %s: %s", account, e)
        except Exception as e:
            log.warning("Failed to list file shares for account %s: %s", account, e)

    if unsupported_accounts:
        print(f"Skipped {unsupported_accounts} account(s) that do not support Azure Files.")

    if not rows:
        print("No file shares found.")
        return

    df = pd.DataFrame(rows)
    filename = utils.create_export_filename(subscription_name, "file-shares", "all")
    utils.save_dataframe_to_excel(df, filename, sheet_name="File Shares")
    print(f"Exported {len(rows)} file share(s) → {filename}")
    log.info("Export complete: %d file shares", len(rows))


if __name__ == "__main__":
    sub_id, sub_name = utils.resolve_target_subscription()
    if not sub_id:
        print("ERROR: No subscription configured. Run configure.py first.")
        sys.exit(1)
    main(sub_id, sub_name)
