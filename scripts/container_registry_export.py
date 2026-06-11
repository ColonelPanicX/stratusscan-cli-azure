#!/usr/bin/env python3
"""StratusScanCLI-Azure — Container Registry (ACR) Export"""

import sys
from pathlib import Path

try:
    import utils
except ImportError:
    sys.path.append(str(Path(__file__).parent.parent))
    import utils

import pandas as pd

utils.setup_logging("container-registry-export")
utils.log_script_start("container_registry_export.py", "Container Registry (ACR) Export")

log = utils.get_logger()


def collect_registries(subscription_id: str) -> list:
    client = utils.get_azure_client("containerregistry", subscription_id)
    log.info("Listing container registries in subscription %s", subscription_id)
    return list(client.registries.list())


def main(subscription_id: str, subscription_name: str) -> None:
    environment = utils.detect_environment()
    if not utils.is_service_available_in_environment("containerregistry", environment):
        sys.exit(0)

    registries = collect_registries(subscription_id)
    if not registries:
        print("No container registries found.")
        return

    rows = []
    for reg in registries:
        sku = reg.sku
        tags = reg.tags or {}
        rows.append({
            "Name": reg.name,
            "Resource Group": utils.extract_resource_group(reg.id),
            "Location": reg.location,
            "SKU": sku.name if sku else "",
            "Tier": str(sku.tier) if sku and getattr(sku, "tier", None) else "",
            "Login Server": reg.login_server or "",
            "Admin User Enabled": "Yes" if reg.admin_user_enabled else "No",
            "Public Network Access": str(getattr(reg, "public_network_access", "")) or "",
            "Anonymous Pull": "Yes" if getattr(reg, "anonymous_pull_enabled", False) else "No",
            "Zone Redundancy": str(getattr(reg, "zone_redundancy", "")) or "",
            "Provisioning State": str(reg.provisioning_state) if reg.provisioning_state else "",
            "Creation Date": str(reg.creation_date) if reg.creation_date else "",
            "Tags": "; ".join(f"{k}={v}" for k, v in tags.items()),
        })

    df = pd.DataFrame(rows)
    filename = utils.create_export_filename(subscription_name, "container-registry", "all")
    utils.save_dataframe_to_excel(df, filename, sheet_name="Container Registries")
    print(f"Exported {len(rows)} container registr(ies) → {filename}")
    log.info("Export complete: %d registries", len(rows))


if __name__ == "__main__":
    cfg = utils.get_config()
    sub_id = cfg.get("default_subscription_id", "")
    sub_name = utils.get_subscription_name(sub_id)
    if not sub_id:
        print("ERROR: No subscription configured. Run configure.py first.")
        sys.exit(1)
    main(sub_id, sub_name)
