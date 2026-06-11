#!/usr/bin/env python3
"""StratusScanCLI-Azure — User-Assigned Managed Identities Export"""

import sys
from pathlib import Path

try:
    import utils
except ImportError:
    sys.path.append(str(Path(__file__).parent.parent))
    import utils

import pandas as pd

utils.setup_logging("managed-identities-export")
utils.log_script_start("managed_identities_export.py", "Managed Identities Export")

log = utils.get_logger()


def collect_identities(subscription_id: str) -> list:
    client = utils.get_azure_client("msi", subscription_id)
    log.info("Listing user-assigned managed identities in subscription %s", subscription_id)
    return list(client.user_assigned_identities.list_by_subscription())


def main(subscription_id: str, subscription_name: str) -> None:
    environment = utils.detect_environment()
    if not utils.is_service_available_in_environment("msi", environment):
        sys.exit(0)

    identities = collect_identities(subscription_id)
    if not identities:
        print("No user-assigned managed identities found.")
        return

    rows = []
    for ident in identities:
        tags = ident.tags or {}
        rows.append({
            "Name": ident.name,
            "Resource Group": utils.extract_resource_group(ident.id),
            "Location": ident.location,
            "Principal ID": str(ident.principal_id) if ident.principal_id else "",
            "Client ID": str(ident.client_id) if ident.client_id else "",
            "Tenant ID": str(ident.tenant_id) if ident.tenant_id else "",
            "Tags": "; ".join(f"{k}={v}" for k, v in tags.items()),
        })

    df = pd.DataFrame(rows)
    filename = utils.create_export_filename(subscription_name, "managed-identities", "all")
    utils.save_dataframe_to_excel(df, filename, sheet_name="Managed Identities")
    print(f"Exported {len(rows)} managed identit(ies) → {filename}")
    log.info("Export complete: %d identities", len(rows))


if __name__ == "__main__":
    sub_id, sub_name = utils.resolve_target_subscription()
    if not sub_id:
        print("ERROR: No subscription configured. Run configure.py first.")
        sys.exit(1)
    main(sub_id, sub_name)
