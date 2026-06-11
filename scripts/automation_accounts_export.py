#!/usr/bin/env python3
"""StratusScanCLI-Azure — Automation Accounts Export"""

import sys
from pathlib import Path

try:
    import utils
except ImportError:
    sys.path.append(str(Path(__file__).parent.parent))
    import utils

import pandas as pd

utils.setup_logging("automation-accounts-export")
utils.log_script_start("automation_accounts_export.py", "Automation Accounts Export")

log = utils.get_logger()


def collect_accounts(subscription_id: str) -> list:
    client = utils.get_azure_client("automation", subscription_id)
    log.info("Listing Automation accounts in subscription %s", subscription_id)
    return list(client.automation_account.list())


def main(subscription_id: str, subscription_name: str) -> None:
    environment = utils.detect_environment()
    if not utils.is_service_available_in_environment("automation", environment):
        sys.exit(0)

    accounts = collect_accounts(subscription_id)
    if not accounts:
        print("No Automation accounts found.")
        return

    rows = []
    for acct in accounts:
        sku = acct.sku
        tags = acct.tags or {}
        rows.append({
            "Name": acct.name,
            "Resource Group": utils.extract_resource_group(acct.id),
            "Location": acct.location,
            "SKU": str(sku.name) if sku else "",
            "State": str(acct.state) if getattr(acct, "state", None) else "",
            "Created": str(acct.creation_time) if getattr(acct, "creation_time", None) else "",
            "Last Modified": str(acct.last_modified_time) if getattr(acct, "last_modified_time", None) else "",
            "Tags": "; ".join(f"{k}={v}" for k, v in tags.items()),
        })

    df = pd.DataFrame(rows)
    filename = utils.create_export_filename(subscription_name, "automation-accounts", "all")
    utils.save_dataframe_to_excel(df, filename, sheet_name="Automation Accounts")
    print(f"Exported {len(rows)} Automation account(s) → {filename}")
    log.info("Export complete: %d accounts", len(rows))


if __name__ == "__main__":
    sub_id, sub_name = utils.resolve_target_subscription()
    if not sub_id:
        print("ERROR: No subscription configured. Run configure.py first.")
        sys.exit(1)
    main(sub_id, sub_name)
