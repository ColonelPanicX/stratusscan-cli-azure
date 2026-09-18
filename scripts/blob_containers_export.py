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
from azure.core.exceptions import HttpResponseError

utils.setup_logging("blob-containers-export")
utils.log_script_start("blob_containers_export.py", "Blob Containers Inventory Export")

log = utils.get_logger()


def _iter_accounts(client):
    for acct in client.storage_accounts.list():
        rg = utils.extract_resource_group(acct.id)
        yield rg, acct.name


def main(subscription_id: str, subscription_name: str) -> utils.ExportResult:
    environment = utils.detect_environment()
    if not utils.is_service_available_in_environment("storage", environment):
        sys.exit(0)

    client = utils.get_azure_client("storage", subscription_id)
    log.info("Listing blob containers across storage accounts in %s", subscription_id)

    rows = []
    errors: list = []
    for rg, account in _iter_accounts(client):
        try:
            for c in client.blob_containers.list(rg, account):
                metadata = getattr(c, "metadata", None) or {}
                rows.append({
                    "Storage Account": account,
                    "Container Name": c.name,
                    "Resource Group": rg,
                    "Public Access Level": utils.s(getattr(c, "public_access", None)) if getattr(c, "public_access", None) else "None",
                    "Lease State": utils.s(getattr(c, "lease_state", None)) if getattr(c, "lease_state", None) else "",
                    "Has Immutability Policy": "Yes" if getattr(c, "has_immutability_policy", False) else "No",
                    "Has Legal Hold": "Yes" if getattr(c, "has_legal_hold", False) else "No",
                    "Default Encryption Scope": getattr(c, "default_encryption_scope", "") or "",
                    "Last Modified": utils.s(getattr(c, "last_modified_time", None)) if getattr(c, "last_modified_time", None) else "",
                    "Metadata": "; ".join(f"{k}={v}" for k, v in metadata.items()),
                })
        except HttpResponseError as e:
            errors.append(utils.error_record(account, "blob_containers.list", e))
            log.warning("Failed to list containers for account %s: %s", account, e)

    if not rows and not errors:
        raise utils.NoResourcesFound("blob containers")

    df = pd.DataFrame(rows)
    filename = utils.create_export_filename(subscription_name, "blob-containers", "all")
    utils.save_dataframe_to_excel(df, filename, sheet_name="Blob Containers", errors=errors)
    print(f"Exported {len(rows)} blob container(s) → {filename}")
    log.info("Export complete: %d containers", len(rows))
    return utils.ExportResult(rows=len(rows), filename=filename, errors=errors)


if __name__ == "__main__":
    import runner

    runner.run_exporter(main, "blob-containers")
