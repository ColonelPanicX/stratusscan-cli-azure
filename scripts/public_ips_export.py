#!/usr/bin/env python3
"""StratusScanCLI-Azure — Public IP Addresses Export"""

import sys
from pathlib import Path

try:
    import utils
except ImportError:
    sys.path.append(str(Path(__file__).parent.parent))
    import utils

import pandas as pd

utils.setup_logging("public-ips-export")
utils.log_script_start("public_ips_export.py", "Azure Public IP Addresses Export")

log = utils.get_logger()

_RESOURCE_TYPE_LABELS = {
    "networkinterfaces": "Network Interface",
    "loadbalancers": "Load Balancer",
    "applicationgateways": "Application Gateway",
    "bastionhosts": "Bastion Host",
    "virtualnetworkgateways": "Virtual Network Gateway",
    "azurefirewalls": "Azure Firewall",
    "natgateways": "NAT Gateway",
}


def collect_public_ips(subscription_id: str) -> list:
    client = utils.get_azure_client("network", subscription_id)
    log.info("Listing all public IPs in subscription %s", subscription_id)
    return list(client.public_ip_addresses.list_all())


def _parse_network_resource(resource_id: str) -> tuple:
    """Return (type label, name) for the Microsoft.Network resource that owns resource_id."""
    parts = resource_id.split("/")
    lowered = [p.lower() for p in parts]
    for i, part in enumerate(lowered):
        if part == "providers" and i + 3 < len(parts) and lowered[i + 1] == "microsoft.network":
            type_segment = parts[i + 2]
            label = _RESOURCE_TYPE_LABELS.get(type_segment.lower(), type_segment)
            return label, parts[i + 3]
    return "", ""


def _association(pip) -> tuple:
    ip_config = pip.ip_configuration
    if ip_config and ip_config.id:
        return _parse_network_resource(ip_config.id)
    nat_gateway = pip.nat_gateway
    if nat_gateway and nat_gateway.id:
        return _RESOURCE_TYPE_LABELS["natgateways"], nat_gateway.id.split("/")[-1]
    return "", ""


def _build_row(pip) -> dict:
    tags = pip.tags or {}
    dns = pip.dns_settings
    resource_type, resource_name = _association(pip)
    return {
        "Name": pip.name,
        "Resource Group": utils.extract_resource_group(pip.id),
        "Location": pip.location,
        "IP Address": pip.ip_address or "Not assigned",
        "Allocation Method": utils.s(pip.public_ip_allocation_method),
        "SKU": utils.s(pip.sku.name) if pip.sku else "",
        "Version": utils.s(pip.public_ip_address_version),
        "DNS Label": dns.domain_name_label if dns and dns.domain_name_label else "",
        "FQDN": dns.fqdn if dns and dns.fqdn else "",
        "Associated Resource": resource_name,
        "Zones": ", ".join(pip.zones) if pip.zones else "",
        "Provisioning State": utils.s(pip.provisioning_state),
        "Tags": "; ".join(f"{k}={v}" for k, v in tags.items()),
        "Associated Resource Type": resource_type,
        "Attached": bool(resource_type),
    }


def main(subscription_id: str, subscription_name: str) -> utils.ExportResult:
    environment = utils.detect_environment()
    if not utils.is_service_available_in_environment("network", environment):
        sys.exit(0)

    pips = collect_public_ips(subscription_id)
    if not pips:
        raise utils.NoResourcesFound("public IP addresses")

    rows = [_build_row(pip) for pip in pips]

    df = pd.DataFrame(rows)
    filename = utils.create_export_filename(subscription_name, "public-ips", "all")
    utils.save_dataframe_to_excel(df, filename, sheet_name="Public IPs")
    print(f"Exported {len(rows)} public IP(s) → {filename}")
    log.info("Export complete: %d public IPs", len(rows))
    return utils.ExportResult(rows=len(rows), filename=filename, errors=[])


if __name__ == "__main__":
    import runner

    runner.run_exporter(main, "public-ips")
