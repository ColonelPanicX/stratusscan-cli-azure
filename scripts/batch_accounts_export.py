#!/usr/bin/env python3
"""StratusScanCLI-Azure — Batch Accounts Export"""

import sys
from pathlib import Path

try:
    import utils
except ImportError:
    sys.path.append(str(Path(__file__).parent.parent))
    import utils

import pandas as pd

utils.setup_logging("batch-accounts-export")
utils.log_script_start("batch_accounts_export.py", "Batch Accounts Export")

log = utils.get_logger()


def collect_accounts(subscription_id: str) -> list:
    client = utils.get_azure_client("batch", subscription_id)
    log.info("Listing Batch accounts in subscription %s", subscription_id)
    return list(client.batch_account.list())


def main(subscription_id: str, subscription_name: str) -> None:
    environment = utils.detect_environment()
    if not utils.is_service_available_in_environment("batch", environment):
        sys.exit(0)

    accounts = collect_accounts(subscription_id)
    if not accounts:
        print("No Batch accounts found.")
        return

    rows = []
    for acct in accounts:
        tags = acct.tags or {}
        rows.append({
            "Name": acct.name,
            "Resource Group": utils.extract_resource_group(acct.id),
            "Location": acct.location,
            "Account Endpoint": getattr(acct, "account_endpoint", "") or "",
            "Provisioning State": str(acct.provisioning_state) if acct.provisioning_state else "",
            "Pool Allocation Mode": str(getattr(acct, "pool_allocation_mode", "")) or "",
            "Dedicated Core Quota": getattr(acct, "dedicated_core_quota", "") if getattr(acct, "dedicated_core_quota", None) is not None else "",
            "Low-Priority Core Quota": getattr(acct, "low_priority_core_quota", "") if getattr(acct, "low_priority_core_quota", None) is not None else "",
            "Public Network Access": str(getattr(acct, "public_network_access", "")) or "",
            "Tags": "; ".join(f"{k}={v}" for k, v in tags.items()),
        })

    df = pd.DataFrame(rows)
    filename = utils.create_export_filename(subscription_name, "batch-accounts", "all")
    utils.save_dataframe_to_excel(df, filename, sheet_name="Batch Accounts")
    print(f"Exported {len(rows)} Batch account(s) → {filename}")
    log.info("Export complete: %d accounts", len(rows))


if __name__ == "__main__":
    cfg = utils.get_config()
    sub_id = cfg.get("default_subscription_id", "")
    sub_name = utils.get_subscription_name(sub_id)
    if not sub_id:
        print("ERROR: No subscription configured. Run configure.py first.")
        sys.exit(1)
    main(sub_id, sub_name)
