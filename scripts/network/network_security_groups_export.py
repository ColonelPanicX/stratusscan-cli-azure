#!/usr/bin/env python3
"""StratusScanCLI-Azure — Network Security Groups Export"""

import sys
from pathlib import Path

try:
    import utils
except ImportError:
    sys.path.append(str(Path(__file__).parent.parent.parent))
    import utils

import pandas as pd

utils.setup_logging("nsg-export")
utils.log_script_start("network_security_groups_export.py", "Azure NSG Export")

log = utils.get_logger()


def collect_nsgs(subscription_id: str) -> list:
    client = utils.get_azure_client("network", subscription_id)
    log.info("Listing all NSGs in subscription %s", subscription_id)
    return list(client.network_security_groups.list_all())


def main(subscription_id: str, subscription_name: str) -> None:
    environment = utils.detect_environment()
    if not utils.is_service_available_in_environment("network", environment):
        sys.exit(0)

    nsgs = collect_nsgs(subscription_id)
    if not nsgs:
        print("No network security groups found.")
        return

    rows = []
    for nsg in nsgs:
        rg = nsg.id.split("/resourceGroups/")[1].split("/")[0] if nsg.id else ""
        tags = nsg.tags or {}
        inbound = len(nsg.security_rules or [])
        default_inbound = len(nsg.default_security_rules or [])
        # Count rules by direction
        inbound_rules = sum(
            1 for r in (nsg.security_rules or [])
            if r.direction and str(r.direction).lower() == "inbound"
        )
        outbound_rules = sum(
            1 for r in (nsg.security_rules or [])
            if r.direction and str(r.direction).lower() == "outbound"
        )
        associated_subnets = len(nsg.subnets or [])
        associated_nics = len(nsg.network_interfaces or [])
        rows.append({
            "Name": nsg.name,
            "Resource Group": rg,
            "Location": nsg.location,
            "Custom Inbound Rules": inbound_rules,
            "Custom Outbound Rules": outbound_rules,
            "Default Rules": default_inbound,
            "Associated Subnets": associated_subnets,
            "Associated NICs": associated_nics,
            "Provisioning State": nsg.provisioning_state or "",
            "Tags": "; ".join(f"{k}={v}" for k, v in tags.items()),
        })

    df = pd.DataFrame(rows)
    filename = utils.create_export_filename(subscription_name, "network-security-groups", "all")
    utils.save_dataframe_to_excel(df, filename, sheet_name="NSGs")
    print(f"Exported {len(rows)} NSG(s) → {filename}")
    log.info("Export complete: %d NSGs", len(rows))


if __name__ == "__main__":
    cfg = utils.get_config()
    sub_id = cfg.get("default_subscription_id", "")
    sub_name = utils.get_subscription_name(sub_id)
    if not sub_id:
        print("ERROR: No subscription configured. Run configure.py first.")
        sys.exit(1)
    main(sub_id, sub_name)
