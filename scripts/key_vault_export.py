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
    client = utils.get_azure_client("keyvault", subscription_id)
    log.info("Listing all key vaults in subscription %s", subscription_id)
    return list(client.vaults.list())


def _get_vault_detail(client, resource_group: str, name: str):
    try:
        return client.vaults.get(resource_group, name)
    except Exception as exc:
        log.warning("Could not get vault detail for %s: %s", name, exc)
        return None


def main(subscription_id: str, subscription_name: str) -> None:
    environment = utils.detect_environment()
    if not utils.is_service_available_in_environment("keyvault", environment):
        sys.exit(0)

    client = utils.get_azure_client("keyvault", subscription_id)
    vaults_summary = collect_vaults(subscription_id)
    if not vaults_summary:
        print("No key vaults found.")
        return

    rows = []
    for vault_ref in vaults_summary:
        rg = vault_ref.id.split("/resourceGroups/")[1].split("/")[0] if vault_ref.id else ""
        vault = _get_vault_detail(client, rg, vault_ref.name)
        if vault is None:
            continue
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
            "Public Network Access": str(props.public_network_access) if props and props.public_network_access else "",
            "Vault URI": props.vault_uri if props else "",
            "Tags": "; ".join(f"{k}={v}" for k, v in tags.items()),
        })

    df = pd.DataFrame(rows)
    filename = utils.create_export_filename(subscription_name, "key-vaults", "all")
    utils.save_dataframe_to_excel(df, filename, sheet_name="Key Vaults")
    print(f"Exported {len(rows)} key vault(s) → {filename}")
    log.info("Export complete: %d vaults", len(rows))


if __name__ == "__main__":
    cfg = utils.get_config()
    sub_id = cfg.get("default_subscription_id", "")
    sub_name = utils.get_subscription_name(sub_id)
    if not sub_id:
        print("ERROR: No subscription configured. Run configure.py first.")
        sys.exit(1)
    main(sub_id, sub_name)
