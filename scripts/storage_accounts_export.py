#!/usr/bin/env python3
"""StratusScanCLI-Azure — Storage Accounts Export"""

import sys
from pathlib import Path
from typing import Any

try:
    import utils
except ImportError:
    sys.path.append(str(Path(__file__).parent.parent))
    import utils

import pandas as pd
from azure.core.exceptions import HttpResponseError

utils.setup_logging("storage-accounts-export")
utils.log_script_start("storage_accounts_export.py", "Azure Storage Accounts Export")

log = utils.get_logger()


def collect_storage_accounts(client) -> list:
    log.info("Listing all storage accounts")
    return list(client.storage_accounts.list())


def collect_blob_service_properties(client, resource_group: str, account_name: str) -> Any:
    """One Storage RP read per account; returns None (blank columns, not False) when it fails."""
    try:
        return client.blob_services.get_service_properties(resource_group, account_name)
    except HttpResponseError as e:
        log.warning("Blob service properties unavailable for %s: %s", account_name, e.message)
        return None


def _flag(value) -> Any:
    return "" if value is None else value


def _replication(sku) -> str:
    name = utils.s(sku.name) if sku else ""
    return name.split("_", 1)[1] if "_" in name else ""


def _retention(policy) -> tuple:
    if policy is None:
        return "", ""
    return _flag(policy.enabled), _flag(policy.days)


def _build_row(acct, blob_props) -> dict:
    tags = acct.tags or {}
    encryption = acct.encryption
    network = acct.network_rule_set
    blob_soft_delete, blob_soft_delete_days = _retention(
        blob_props.delete_retention_policy if blob_props else None
    )
    container_soft_delete, container_soft_delete_days = _retention(
        blob_props.container_delete_retention_policy if blob_props else None
    )
    return {
        "Name": acct.name,
        "Resource Group": utils.extract_resource_group(acct.id),
        "Location": acct.location,
        "SKU": utils.s(acct.sku.name) if acct.sku else "",
        "Kind": utils.s(acct.kind),
        "Access Tier": utils.s(acct.access_tier),
        "HTTPS Only": _flag(acct.enable_https_traffic_only),
        "Performance Tier": utils.s(acct.sku.tier) if acct.sku else "",
        "Public Network Access": utils.s(acct.public_network_access),
        "Minimum TLS Version": utils.s(acct.minimum_tls_version),
        "Blob Soft Delete": blob_soft_delete,
        "Allow Blob Public Access": _flag(acct.allow_blob_public_access),
        "Provisioning State": utils.s(acct.provisioning_state),
        "Tags": "; ".join(f"{k}={v}" for k, v in tags.items()),
        "Replication": _replication(acct.sku),
        "Blob Soft Delete Days": blob_soft_delete_days,
        "Container Soft Delete": container_soft_delete,
        "Container Soft Delete Days": container_soft_delete_days,
        "Allow Shared Key Access": _flag(acct.allow_shared_key_access),
        "Infrastructure Encryption": _flag(
            encryption.require_infrastructure_encryption if encryption else None
        ),
        "Encryption Key Source": utils.s(encryption.key_source) if encryption else "",
        "Network Default Action": utils.s(network.default_action) if network else "",
        "Network Bypass": utils.s(network.bypass) if network else "",
        "Allow Cross-Tenant Replication": _flag(acct.allow_cross_tenant_replication),
    }


def main(subscription_id: str, subscription_name: str) -> utils.ExportResult:
    environment = utils.detect_environment()
    if not utils.is_service_available_in_environment("storage", environment):
        sys.exit(0)

    client = utils.get_azure_client("storage", subscription_id)
    accounts = collect_storage_accounts(client)
    if not accounts:
        raise utils.NoResourcesFound("storage accounts")

    rows = []
    for acct in accounts:
        rg = utils.extract_resource_group(acct.id)
        blob_props = collect_blob_service_properties(client, rg, acct.name)
        rows.append(_build_row(acct, blob_props))

    df = pd.DataFrame(rows)
    filename = utils.create_export_filename(subscription_name, "storage-accounts", "all")
    utils.save_dataframe_to_excel(df, filename, sheet_name="Storage Accounts")
    print(f"Exported {len(rows)} storage account(s) → {filename}")
    log.info("Export complete: %d storage accounts", len(rows))
    return utils.ExportResult(rows=len(rows), filename=filename, errors=[])


if __name__ == "__main__":
    import runner

    runner.run_exporter(main, "storage-accounts")
