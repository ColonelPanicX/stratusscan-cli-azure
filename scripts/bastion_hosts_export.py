#!/usr/bin/env python3
"""StratusScanCLI-Azure — Bastion Hosts Export"""

import sys
from pathlib import Path

try:
    import utils
except ImportError:
    sys.path.append(str(Path(__file__).parent.parent))
    import utils

import pandas as pd

utils.setup_logging("bastion-hosts-export")
utils.log_script_start("bastion_hosts_export.py", "Bastion Hosts Export")

log = utils.get_logger()


def collect_bastion_hosts(subscription_id: str) -> list:
    client = utils.get_azure_client("network", subscription_id)
    log.info("Listing all bastion hosts in subscription %s", subscription_id)
    return list(client.bastion_hosts.list())


def _ip_config(bastion):
    configs = getattr(bastion, "ip_configurations", None) or []
    return configs[0] if configs else None


def _vnet_and_subnet(bastion) -> tuple:
    cfg = _ip_config(bastion)
    subnet_id = getattr(getattr(cfg, "subnet", None), "id", "") or "" if cfg else ""
    if not subnet_id:
        return "", ""
    subnet = subnet_id.split("/")[-1]
    vnet = ""
    if "/virtualNetworks/" in subnet_id:
        vnet = subnet_id.split("/virtualNetworks/")[1].split("/")[0]
    return vnet, subnet


def _public_ip(bastion) -> str:
    cfg = _ip_config(bastion)
    pip_id = getattr(getattr(cfg, "public_ip_address", None), "id", "") or "" if cfg else ""
    return pip_id.split("/")[-1] if pip_id else ""


def main(subscription_id: str, subscription_name: str) -> None:
    environment = utils.detect_environment()
    if not utils.is_service_available_in_environment("network", environment):
        sys.exit(0)

    hosts = collect_bastion_hosts(subscription_id)
    if not hosts:
        print("No bastion hosts found.")
        return

    rows = []
    for bastion in hosts:
        rg = bastion.id.split("/resourceGroups/")[1].split("/")[0] if bastion.id else ""
        vnet, subnet = _vnet_and_subnet(bastion)
        tags = bastion.tags or {}
        rows.append({
            "Name": bastion.name,
            "Resource Group": rg,
            "Location": bastion.location,
            "SKU": bastion.sku.name if bastion.sku else "",
            "DNS Name": getattr(bastion, "dns_name", "") or "",
            "VNet": vnet,
            "Subnet": subnet,
            "Public IP": _public_ip(bastion),
            "Scale Units": getattr(bastion, "scale_units", "") if getattr(bastion, "scale_units", None) is not None else "",
            "Provisioning State": bastion.provisioning_state or "",
            "Tags": "; ".join(f"{k}={v}" for k, v in tags.items()),
        })

    df = pd.DataFrame(rows)
    filename = utils.create_export_filename(subscription_name, "bastion-hosts", "all")
    utils.save_dataframe_to_excel(df, filename, sheet_name="Bastion Hosts")
    print(f"Exported {len(rows)} bastion host(s) → {filename}")
    log.info("Export complete: %d bastion hosts", len(rows))


if __name__ == "__main__":
    sub_id, sub_name = utils.resolve_target_subscription()
    if not sub_id:
        print("ERROR: No subscription configured. Run configure.py first.")
        sys.exit(1)
    main(sub_id, sub_name)
