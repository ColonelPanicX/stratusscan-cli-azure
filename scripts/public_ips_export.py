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


def collect_public_ips(subscription_id: str) -> list:
    client = utils.get_azure_client("network", subscription_id)
    log.info("Listing all public IPs in subscription %s", subscription_id)
    return list(client.public_ip_addresses.list_all())


def _associated_resource(pip) -> str:
    """Return the name of the resource this IP is associated with."""
    try:
        if pip.ip_configuration and pip.ip_configuration.id:
            parts = pip.ip_configuration.id.split("/")
            # .../resourceGroups/rg/providers/Microsoft.Network/networkInterfaces/nic/...
            if "networkInterfaces" in parts:
                return parts[parts.index("networkInterfaces") + 1]
            if "loadBalancers" in parts:
                return parts[parts.index("loadBalancers") + 1]
    except Exception:
        pass
    return ""


def main(subscription_id: str, subscription_name: str) -> None:
    environment = utils.detect_environment()
    if not utils.is_service_available_in_environment("network", environment):
        sys.exit(0)

    pips = collect_public_ips(subscription_id)
    if not pips:
        print("No public IP addresses found.")
        return

    rows = []
    for pip in pips:
        rg = utils.extract_resource_group(pip.id)
        tags = pip.tags or {}
        rows.append({
            "Name": pip.name,
            "Resource Group": rg,
            "Location": pip.location,
            "IP Address": pip.ip_address or "Not assigned",
            "Allocation Method": str(pip.public_ip_allocation_method) if pip.public_ip_allocation_method else "",
            "SKU": pip.sku.name if pip.sku else "",
            "Version": str(pip.public_ip_address_version) if pip.public_ip_address_version else "",
            "DNS Label": (
                pip.dns_settings.domain_name_label
                if pip.dns_settings and pip.dns_settings.domain_name_label
                else ""
            ),
            "FQDN": (
                pip.dns_settings.fqdn
                if pip.dns_settings and pip.dns_settings.fqdn
                else ""
            ),
            "Associated Resource": _associated_resource(pip),
            "Zones": ", ".join(pip.zones) if pip.zones else "",
            "Provisioning State": pip.provisioning_state or "",
            "Tags": "; ".join(f"{k}={v}" for k, v in tags.items()),
        })

    df = pd.DataFrame(rows)
    filename = utils.create_export_filename(subscription_name, "public-ips", "all")
    utils.save_dataframe_to_excel(df, filename, sheet_name="Public IPs")
    print(f"Exported {len(rows)} public IP(s) → {filename}")
    log.info("Export complete: %d public IPs", len(rows))


if __name__ == "__main__":
    sub_id, sub_name = utils.resolve_target_subscription()
    if not sub_id:
        print("ERROR: No subscription configured. Run configure.py first.")
        sys.exit(1)
    main(sub_id, sub_name)
