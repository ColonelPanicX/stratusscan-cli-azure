#!/usr/bin/env python3
"""StratusScanCLI-Azure — NAT Gateways Export"""

import sys
from pathlib import Path

try:
    import utils
except ImportError:
    sys.path.append(str(Path(__file__).parent.parent))
    import utils

import pandas as pd

utils.setup_logging("nat-gateways-export")
utils.log_script_start("nat_gateways_export.py", "NAT Gateways Export")

log = utils.get_logger()


def collect_nat_gateways(subscription_id: str) -> list:
    client = utils.get_azure_client("network", subscription_id)
    log.info("Listing all NAT gateways in subscription %s", subscription_id)
    return list(client.nat_gateways.list_all())


def _names(sub_resources) -> str:
    names = []
    for r in sub_resources or []:
        rid = getattr(r, "id", "") or ""
        if rid:
            names.append(rid.split("/")[-1])
    return ", ".join(names)


def main(subscription_id: str, subscription_name: str) -> None:
    environment = utils.detect_environment()
    if not utils.is_service_available_in_environment("network", environment):
        sys.exit(0)

    gateways = collect_nat_gateways(subscription_id)
    if not gateways:
        print("No NAT gateways found.")
        return

    rows = []
    for gw in gateways:
        rg = gw.id.split("/resourceGroups/")[1].split("/")[0] if gw.id else ""
        tags = gw.tags or {}
        rows.append({
            "Name": gw.name,
            "Resource Group": rg,
            "Location": gw.location,
            "SKU": gw.sku.name if gw.sku else "",
            "Idle Timeout": gw.idle_timeout_in_minutes if gw.idle_timeout_in_minutes is not None else "",
            "Public IP Addresses": _names(getattr(gw, "public_ip_addresses", None)),
            "Public IP Prefixes": _names(getattr(gw, "public_ip_prefixes", None)),
            "Subnets": _names(getattr(gw, "subnets", None)),
            "Provisioning State": gw.provisioning_state or "",
            "Tags": "; ".join(f"{k}={v}" for k, v in tags.items()),
        })

    df = pd.DataFrame(rows)
    filename = utils.create_export_filename(subscription_name, "nat-gateways", "all")
    utils.save_dataframe_to_excel(df, filename, sheet_name="NAT Gateways")
    print(f"Exported {len(rows)} NAT gateway(s) → {filename}")
    log.info("Export complete: %d NAT gateways", len(rows))


if __name__ == "__main__":
    cfg = utils.get_config()
    sub_id = cfg.get("default_subscription_id", "")
    sub_name = utils.get_subscription_name(sub_id)
    if not sub_id:
        print("ERROR: No subscription configured. Run configure.py first.")
        sys.exit(1)
    main(sub_id, sub_name)
