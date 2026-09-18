#!/usr/bin/env python3
"""StratusScanCLI-Azure — Subnets Export"""

import sys
from pathlib import Path

try:
    import utils
except ImportError:
    sys.path.append(str(Path(__file__).parent.parent))
    import utils

import pandas as pd

log = utils.get_logger()


def _name_of(sub_resource) -> str:
    return sub_resource.id.split("/")[-1] if sub_resource and sub_resource.id else ""


def _address_prefix(subnet) -> str:
    return subnet.address_prefix or ", ".join(subnet.address_prefixes or [])


def _build_row(vnet, subnet) -> dict:
    nsg_name = _name_of(subnet.network_security_group)
    delegations = [d.service_name for d in (subnet.delegations or []) if d.service_name]
    return {
        "VNet Name": vnet.name,
        "VNet Resource Group": utils.extract_resource_group(vnet.id),
        "Subnet Name": subnet.name,
        "Address Prefix": _address_prefix(subnet),
        "NSG": nsg_name,
        "Route Table": _name_of(subnet.route_table),
        "Provisioning State": utils.s(subnet.provisioning_state),
        "Location": vnet.location,
        "No NSG": not nsg_name,
        "NAT Gateway": _name_of(subnet.nat_gateway),
        "Delegations": ", ".join(delegations),
        "Service Endpoint Count": len(subnet.service_endpoints or []),
        "Default Outbound Access": "" if subnet.default_outbound_access is None else subnet.default_outbound_access,
    }


def collect_subnets(subscription_id: str) -> list:
    client = utils.get_azure_client("network", subscription_id)
    vnets = list(client.virtual_networks.list_all())
    log.info("Scanning subnets across %d VNets", len(vnets))
    return [_build_row(vnet, subnet) for vnet in vnets for subnet in (vnet.subnets or [])]


def main(subscription_id: str, subscription_name: str) -> utils.ExportResult:
    environment = utils.detect_environment()
    if not utils.is_service_available_in_environment("network", environment):
        sys.exit(0)

    rows = collect_subnets(subscription_id)
    if not rows:
        raise utils.NoResourcesFound("subnets")

    df = pd.DataFrame(rows)
    filename = utils.create_export_filename(subscription_name, "subnets", "all")
    utils.save_dataframe_to_excel(df, filename, sheet_name="Subnets")
    print(f"Exported {len(rows)} subnet(s) → {filename}")
    log.info("Export complete: %d subnets", len(rows))
    return utils.ExportResult(rows=len(rows), filename=filename, errors=[])


if __name__ == "__main__":
    import runner

    runner.run_exporter(main, "subnets")
