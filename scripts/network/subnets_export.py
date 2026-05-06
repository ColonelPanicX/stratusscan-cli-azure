#!/usr/bin/env python3
"""StratusScanCLI-Azure — Subnets Export"""

import sys
from pathlib import Path

try:
    import utils
except ImportError:
    sys.path.append(str(Path(__file__).parent.parent.parent))
    import utils

import pandas as pd

utils.setup_logging("subnets-export")
utils.log_script_start("subnets_export.py", "Azure Subnets Export")

log = utils.get_logger()


def collect_subnets(subscription_id: str) -> list:
    client = utils.get_azure_client("network", subscription_id)
    vnets = list(client.virtual_networks.list_all())
    log.info("Scanning subnets across %d VNets", len(vnets))
    rows = []
    for vnet in vnets:
        vnet_rg = vnet.id.split("/resourceGroups/")[1].split("/")[0] if vnet.id else ""
        for subnet in (vnet.subnets or []):
            nsg_name = ""
            if subnet.network_security_group and subnet.network_security_group.id:
                nsg_name = subnet.network_security_group.id.split("/")[-1]
            route_table = ""
            if subnet.route_table and subnet.route_table.id:
                route_table = subnet.route_table.id.split("/")[-1]
            rows.append({
                "VNet Name": vnet.name,
                "VNet Resource Group": vnet_rg,
                "Subnet Name": subnet.name,
                "Address Prefix": subnet.address_prefix or "",
                "NSG": nsg_name,
                "Route Table": route_table,
                "Provisioning State": subnet.provisioning_state or "",
                "Location": vnet.location,
            })
    return rows


def main(subscription_id: str, subscription_name: str) -> None:
    environment = utils.detect_environment()
    if not utils.is_service_available_in_environment("network", environment):
        sys.exit(0)

    rows = collect_subnets(subscription_id)
    if not rows:
        print("No subnets found.")
        return

    df = pd.DataFrame(rows)
    filename = utils.create_export_filename(subscription_name, "subnets", "all")
    utils.save_dataframe_to_excel(df, filename, sheet_name="Subnets")
    print(f"Exported {len(rows)} subnet(s) → {filename}")
    log.info("Export complete: %d subnets", len(rows))


if __name__ == "__main__":
    cfg = utils.get_config()
    sub_id = cfg.get("default_subscription_id", "")
    sub_name = utils.get_subscription_name(sub_id)
    if not sub_id:
        print("ERROR: No subscription configured. Run configure.py first.")
        sys.exit(1)
    main(sub_id, sub_name)
