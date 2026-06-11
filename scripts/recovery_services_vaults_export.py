#!/usr/bin/env python3
"""StratusScanCLI-Azure — Recovery Services Vaults Export (Azure Backup / ASR)"""

import sys
from pathlib import Path

try:
    import utils
except ImportError:
    sys.path.append(str(Path(__file__).parent.parent))
    import utils

import pandas as pd

utils.setup_logging("recovery-services-vaults-export")
utils.log_script_start("recovery_services_vaults_export.py", "Recovery Services Vaults Export")

log = utils.get_logger()


def collect_vaults(subscription_id: str) -> list:
    client = utils.get_azure_client("recoveryservices", subscription_id)
    log.info("Listing Recovery Services vaults in subscription %s", subscription_id)
    return list(client.vaults.list_by_subscription_id())


def main(subscription_id: str, subscription_name: str) -> None:
    environment = utils.detect_environment()
    if not utils.is_service_available_in_environment("recoveryservices", environment):
        sys.exit(0)

    vaults = collect_vaults(subscription_id)
    if not vaults:
        print("No Recovery Services vaults found.")
        return

    rows = []
    for vault in vaults:
        sku = vault.sku
        props = vault.properties
        tags = vault.tags or {}
        rows.append({
            "Name": vault.name,
            "Resource Group": utils.extract_resource_group(vault.id),
            "Location": vault.location,
            "SKU": str(sku.name) if sku else "",
            "Tier": str(getattr(sku, "tier", "")) if sku else "",
            "Provisioning State": str(getattr(props, "provisioning_state", "")) if props else "",
            "Public Network Access": str(getattr(props, "public_network_access", "")) if props else "",
            "Tags": "; ".join(f"{k}={v}" for k, v in tags.items()),
        })

    df = pd.DataFrame(rows)
    filename = utils.create_export_filename(subscription_name, "recovery-services-vaults", "all")
    utils.save_dataframe_to_excel(df, filename, sheet_name="Recovery Services Vaults")
    print(f"Exported {len(rows)} Recovery Services vault(s) → {filename}")
    log.info("Export complete: %d vaults", len(rows))


if __name__ == "__main__":
    cfg = utils.get_config()
    sub_id = cfg.get("default_subscription_id", "")
    sub_name = utils.get_subscription_name(sub_id)
    if not sub_id:
        print("ERROR: No subscription configured. Run configure.py first.")
        sys.exit(1)
    main(sub_id, sub_name)
