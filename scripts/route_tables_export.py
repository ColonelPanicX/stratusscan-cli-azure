#!/usr/bin/env python3
"""StratusScanCLI-Azure — Route Tables Export"""

import sys
from pathlib import Path

try:
    import utils
except ImportError:
    sys.path.append(str(Path(__file__).parent.parent))
    import utils

import pandas as pd

utils.setup_logging("route-tables-export")
utils.log_script_start("route_tables_export.py", "Azure Route Tables Export")

log = utils.get_logger()


def collect_route_tables(subscription_id: str) -> list:
    client = utils.get_azure_client("network", subscription_id)
    log.info("Listing all route tables in subscription %s", subscription_id)
    return list(client.route_tables.list_all())


def main(subscription_id: str, subscription_name: str) -> None:
    environment = utils.detect_environment()
    if not utils.is_service_available_in_environment("network", environment):
        sys.exit(0)

    tables = collect_route_tables(subscription_id)
    if not tables:
        print("No route tables found.")
        return

    rows = []
    for rt in tables:
        rg = utils.extract_resource_group(rt.id)
        tags = rt.tags or {}
        routes = rt.routes or []
        associated_subnets = len(rt.subnets or [])
        rows.append({
            "Name": rt.name,
            "Resource Group": rg,
            "Location": rt.location,
            "Route Count": len(routes),
            "Associated Subnets": associated_subnets,
            "Disable BGP Route Propagation": rt.disable_bgp_route_propagation,
            "Provisioning State": rt.provisioning_state or "",
            "Tags": "; ".join(f"{k}={v}" for k, v in tags.items()),
        })

    df = pd.DataFrame(rows)
    filename = utils.create_export_filename(subscription_name, "route-tables", "all")
    utils.save_dataframe_to_excel(df, filename, sheet_name="Route Tables")
    print(f"Exported {len(rows)} route table(s) → {filename}")
    log.info("Export complete: %d route tables", len(rows))


if __name__ == "__main__":
    cfg = utils.get_config()
    sub_id = cfg.get("default_subscription_id", "")
    sub_name = utils.get_subscription_name(sub_id)
    if not sub_id:
        print("ERROR: No subscription configured. Run configure.py first.")
        sys.exit(1)
    main(sub_id, sub_name)
