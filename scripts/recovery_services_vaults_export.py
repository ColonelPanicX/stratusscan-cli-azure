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

log = utils.get_logger()


def collect_vaults(subscription_id: str) -> list:
    client = utils.get_azure_client("recoveryservices", subscription_id)
    log.info("Listing Recovery Services vaults in subscription %s", subscription_id)
    return list(client.vaults.list_by_subscription_id())


def main(subscription_id: str, subscription_name: str) -> utils.ExportResult:
    environment = utils.detect_environment()
    if not utils.is_service_available_in_environment("recoveryservices", environment):
        sys.exit(0)

    vaults = collect_vaults(subscription_id)
    if not vaults:
        raise utils.NoResourcesFound("Recovery Services vaults")

    rows = []
    for vault in vaults:
        sku = vault.sku
        props = vault.properties
        tags = vault.tags or {}
        rows.append({
            "Name": vault.name,
            "Resource Group": utils.extract_resource_group(vault.id),
            "Location": vault.location,
            "SKU": utils.s(sku.name) if sku else "",
            "Tier": utils.s(getattr(sku, "tier", None)) if sku else "",
            "Provisioning State": utils.s(getattr(props, "provisioning_state", None)) if props else "",
            "Public Network Access": utils.s(getattr(props, "public_network_access", None)) if props else "",
            "Tags": "; ".join(f"{k}={v}" for k, v in tags.items()),
        })

    df = pd.DataFrame(rows)
    filename = utils.create_export_filename(subscription_name, "recovery-services-vaults", "all")
    utils.save_dataframe_to_excel(df, filename, sheet_name="Recovery Services Vaults")
    print(f"Exported {len(rows)} Recovery Services vault(s) → {filename}")
    log.info("Export complete: %d vaults", len(rows))
    return utils.ExportResult(rows=len(rows), filename=filename, errors=[])


if __name__ == "__main__":
    import runner

    runner.run_exporter(main, "recovery-services-vaults")
