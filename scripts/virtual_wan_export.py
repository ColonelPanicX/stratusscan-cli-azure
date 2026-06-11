#!/usr/bin/env python3
"""StratusScanCLI-Azure — Virtual WAN & Virtual Hubs Export"""

import sys
from pathlib import Path

try:
    import utils
except ImportError:
    sys.path.append(str(Path(__file__).parent.parent))
    import utils

import pandas as pd

utils.setup_logging("virtual-wan-export")
utils.log_script_start("virtual_wan_export.py", "Virtual WAN & Virtual Hubs Export")

log = utils.get_logger()


def collect_wans(subscription_id: str) -> list:
    client = utils.get_azure_client("network", subscription_id)
    log.info("Listing all virtual WANs in subscription %s", subscription_id)
    return list(client.virtual_wans.list())


def collect_hubs(subscription_id: str) -> list:
    client = utils.get_azure_client("network", subscription_id)
    log.info("Listing all virtual hubs in subscription %s", subscription_id)
    return list(client.virtual_hubs.list())


def main(subscription_id: str, subscription_name: str) -> None:
    environment = utils.detect_environment()
    if not utils.is_service_available_in_environment("network", environment):
        sys.exit(0)

    wans = collect_wans(subscription_id)
    hubs = collect_hubs(subscription_id)

    if not wans and not hubs:
        print("No virtual WANs or hubs found.")
        return

    wan_rows = []
    for wan in wans:
        rg = wan.id.split("/resourceGroups/")[1].split("/")[0] if wan.id else ""
        tags = wan.tags or {}
        wan_rows.append({
            "Name": wan.name,
            "Resource Group": rg,
            "Location": wan.location,
            "Type": getattr(wan, "type_properties_type", "") or getattr(wan, "office365_local_breakout_category", "") or "",
            "Provisioning State": wan.provisioning_state or "",
            "Tags": "; ".join(f"{k}={v}" for k, v in tags.items()),
        })

    hub_rows = []
    for hub in hubs:
        rg = hub.id.split("/resourceGroups/")[1].split("/")[0] if hub.id else ""
        wan_id = getattr(getattr(hub, "virtual_wan", None), "id", "") or ""
        tags = hub.tags or {}
        hub_rows.append({
            "Name": hub.name,
            "Resource Group": rg,
            "Location": hub.location,
            "Virtual WAN": wan_id.split("/")[-1] if wan_id else "",
            "Address Prefix": getattr(hub, "address_prefix", "") or "",
            "SKU": getattr(hub, "sku", "") or "",
            "Routing State": getattr(hub, "routing_state", "") or "",
            "Provisioning State": hub.provisioning_state or "",
            "Tags": "; ".join(f"{k}={v}" for k, v in tags.items()),
        })

    sheets = {}
    if wan_rows:
        sheets["Virtual WANs"] = pd.DataFrame(wan_rows)
    if hub_rows:
        sheets["Virtual Hubs"] = pd.DataFrame(hub_rows)

    filename = utils.create_export_filename(subscription_name, "virtual-wan", "all")
    utils.save_multiple_dataframes_to_excel(sheets, filename)
    print(f"Exported {len(wan_rows)} virtual WAN(s), {len(hub_rows)} virtual hub(s) → {filename}")
    log.info("Export complete: %d WANs, %d hubs", len(wan_rows), len(hub_rows))


if __name__ == "__main__":
    sub_id, sub_name = utils.resolve_target_subscription()
    if not sub_id:
        print("ERROR: No subscription configured. Run configure.py first.")
        sys.exit(1)
    main(sub_id, sub_name)
