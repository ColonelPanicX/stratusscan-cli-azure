#!/usr/bin/env python3
"""StratusScanCLI-Azure — Key Vault Export"""

import sys
from pathlib import Path

try:
    import utils
except ImportError:
    sys.path.append(str(Path(__file__).parent.parent))
    import utils

import pandas as pd

utils.setup_logging("key-vault-export")
utils.log_script_start("key_vault_export.py", "Azure Key Vault Export")

log = utils.get_logger()


def collect_vaults(subscription_id: str) -> list:
    """vaults.list_by_subscription returns full Vault models with properties; vaults.list returns bare TrackedResource."""
    client = utils.get_azure_client("keyvault", subscription_id)
    log.info("Listing all key vaults in subscription %s", subscription_id)
    return list(client.vaults.list_by_subscription())


def main(subscription_id: str, subscription_name: str) -> utils.ExportResult:
    environment = utils.detect_environment()
    if not utils.is_service_available_in_environment("keyvault", environment):
        sys.exit(0)

    vaults = collect_vaults(subscription_id)
    if not vaults:
        raise utils.NoResourcesFound("key vaults")

    rows = []
    errors: list = []
    for vault in vaults:
        rg = utils.extract_resource_group(vault.id)
        props = vault.properties
        tags = vault.tags or {}
        rows.append({
            "Name": vault.name,
            "Resource Group": rg,
            "Location": vault.location,
            "SKU": props.sku.name if props and props.sku else "",
            "Soft Delete Enabled": props.enable_soft_delete if props else "",
            "Soft Delete Retention Days": props.soft_delete_retention_in_days if props else "",
            "Purge Protection Enabled": props.enable_purge_protection if props else "",
            "RBAC Authorization": props.enable_rbac_authorization if props else "",
            "Public Network Access": utils.s(props.public_network_access) if props and props.public_network_access else "",
            "Vault URI": props.vault_uri if props else "",
            "Tags": "; ".join(f"{k}={v}" for k, v in tags.items()),
        })

    df = pd.DataFrame(rows)
    filename = utils.create_export_filename(subscription_name, "key-vaults", "all")
    utils.save_dataframe_to_excel(df, filename, sheet_name="Key Vaults", errors=errors)
    print(f"Exported {len(rows)} key vault(s) → {filename}")
    log.info("Export complete: %d vaults", len(rows))
    return utils.ExportResult(rows=len(rows), filename=filename, errors=errors)


if __name__ == "__main__":
    import runner

    runner.run_exporter(main, "key-vault")
