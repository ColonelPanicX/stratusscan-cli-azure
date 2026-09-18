#!/usr/bin/env python3
"""StratusScanCLI-Azure — VNet Peerings Export"""

import sys
from pathlib import Path

try:
    import utils
except ImportError:
    sys.path.append(str(Path(__file__).parent.parent))
    import utils

import pandas as pd

log = utils.get_logger()


def collect_peerings(subscription_id: str) -> list:
    client = utils.get_azure_client("network", subscription_id)
    vnets = list(client.virtual_networks.list_all())
    log.info("Scanning peerings across %d VNets", len(vnets))
    rows = []
    for vnet in vnets:
        vnet_rg = utils.extract_resource_group(vnet.id)
        for peering in (vnet.virtual_network_peerings or []):
            remote_vnet = ""
            if peering.remote_virtual_network and peering.remote_virtual_network.id:
                remote_vnet = peering.remote_virtual_network.id.split("/")[-1]
            rows.append({
                "Local VNet": vnet.name,
                "Local Resource Group": vnet_rg,
                "Local Location": vnet.location,
                "Peering Name": peering.name,
                "Remote VNet": remote_vnet,
                "Remote VNet ID": (
                    peering.remote_virtual_network.id
                    if peering.remote_virtual_network else ""
                ),
                "Peering State": utils.s(peering.peering_state),
                "Allow VNet Access": peering.allow_virtual_network_access,
                "Allow Forwarded Traffic": peering.allow_forwarded_traffic,
                "Allow Gateway Transit": peering.allow_gateway_transit,
                "Use Remote Gateways": peering.use_remote_gateways,
                "Provisioning State": peering.provisioning_state or "",
            })
    return rows


def main(subscription_id: str, subscription_name: str) -> utils.ExportResult:
    environment = utils.detect_environment()
    if not utils.is_service_available_in_environment("network", environment):
        sys.exit(0)

    rows = collect_peerings(subscription_id)
    if not rows:
        raise utils.NoResourcesFound("VNet peerings")

    df = pd.DataFrame(rows)
    filename = utils.create_export_filename(subscription_name, "vnet-peerings", "all")
    utils.save_dataframe_to_excel(df, filename, sheet_name="VNet Peerings")
    print(f"Exported {len(rows)} VNet peering(s) → {filename}")
    log.info("Export complete: %d peerings", len(rows))
    return utils.ExportResult(rows=len(rows), filename=filename, errors=[])


if __name__ == "__main__":
    import runner

    runner.run_exporter(main, "vnet-peerings")
