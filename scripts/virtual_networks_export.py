#!/usr/bin/env python3
"""StratusScanCLI-Azure — Virtual Networks Export"""

import sys
from pathlib import Path

try:
    import utils
except ImportError:
    sys.path.append(str(Path(__file__).parent.parent))
    import utils

import pandas as pd

utils.setup_logging("virtual-networks-export")
utils.log_script_start("virtual_networks_export.py", "Azure Virtual Networks Export")

log = utils.get_logger()


def collect_vnets(subscription_id: str) -> list:
    client = utils.get_azure_client("network", subscription_id)
    log.info("Listing all VNets in subscription %s", subscription_id)
    return list(client.virtual_networks.list_all())


def main(subscription_id: str, subscription_name: str) -> None:
    environment = utils.detect_environment()
    if not utils.is_service_available_in_environment("network", environment):
        sys.exit(0)

    vnets = collect_vnets(subscription_id)
    if not vnets:
        print("No virtual networks found.")
        return

    rows = []
    for vnet in vnets:
        rg = vnet.id.split("/resourceGroups/")[1].split("/")[0] if vnet.id else ""
        tags = vnet.tags or {}
        address_space = ", ".join(
            vnet.address_space.address_prefixes
        ) if vnet.address_space and vnet.address_space.address_prefixes else ""
        dns_servers = ", ".join(
            vnet.dhcp_options.dns_servers
        ) if vnet.dhcp_options and vnet.dhcp_options.dns_servers else ""
        subnet_count = len(vnet.subnets) if vnet.subnets else 0
        rows.append({
            "Name": vnet.name,
            "Resource Group": rg,
            "Location": vnet.location,
            "Address Space": address_space,
            "DNS Servers": dns_servers,
            "Subnet Count": subnet_count,
            "Provisioning State": vnet.provisioning_state or "",
            "Tags": "; ".join(f"{k}={v}" for k, v in tags.items()),
        })

    df = pd.DataFrame(rows)
    filename = utils.create_export_filename(subscription_name, "virtual-networks", "all")
    utils.save_dataframe_to_excel(df, filename, sheet_name="Virtual Networks")
    print(f"Exported {len(rows)} virtual network(s) → {filename}")
    log.info("Export complete: %d VNets", len(rows))


if __name__ == "__main__":
    cfg = utils.get_config()
    sub_id = cfg.get("default_subscription_id", "")
    sub_name = utils.get_subscription_name(sub_id)
    if not sub_id:
        print("ERROR: No subscription configured. Run configure.py first.")
        sys.exit(1)
    main(sub_id, sub_name)
