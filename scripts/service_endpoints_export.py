#!/usr/bin/env python3
"""StratusScanCLI-Azure — Service Endpoints Inventory Export"""

import sys
from pathlib import Path

try:
    import utils
except ImportError:
    sys.path.append(str(Path(__file__).parent.parent))
    import utils

import pandas as pd

utils.setup_logging("service-endpoints-export")
utils.log_script_start("service_endpoints_export.py", "Service Endpoints Inventory Export")

log = utils.get_logger()


def collect_vnets(subscription_id: str) -> list:
    client = utils.get_azure_client("network", subscription_id)
    log.info("Listing all virtual networks in subscription %s", subscription_id)
    return list(client.virtual_networks.list_all())


def main(subscription_id: str, subscription_name: str) -> None:
    environment = utils.detect_environment()
    if not utils.is_service_available_in_environment("network", environment):
        sys.exit(0)

    vnets = collect_vnets(subscription_id)

    rows = []
    for vnet in vnets:
        rg = vnet.id.split("/resourceGroups/")[1].split("/")[0] if vnet.id else ""
        for subnet in getattr(vnet, "subnets", None) or []:
            for endpoint in getattr(subnet, "service_endpoints", None) or []:
                rows.append({
                    "VNet Name": vnet.name,
                    "Subnet Name": subnet.name,
                    "Resource Group": rg,
                    "Service": getattr(endpoint, "service", "") or "",
                    "Locations": ", ".join(getattr(endpoint, "locations", None) or []),
                    "Provisioning State": getattr(endpoint, "provisioning_state", "") or "",
                })

    if not rows:
        print("No service endpoints found.")
        return

    df = pd.DataFrame(rows)
    filename = utils.create_export_filename(subscription_name, "service-endpoints", "all")
    utils.save_dataframe_to_excel(df, filename, sheet_name="Service Endpoints")
    print(f"Exported {len(rows)} service endpoint(s) → {filename}")
    log.info("Export complete: %d service endpoints", len(rows))


if __name__ == "__main__":
    cfg = utils.get_config()
    sub_id = cfg.get("default_subscription_id", "")
    sub_name = utils.get_subscription_name(sub_id)
    if not sub_id:
        print("ERROR: No subscription configured. Run configure.py first.")
        sys.exit(1)
    main(sub_id, sub_name)
