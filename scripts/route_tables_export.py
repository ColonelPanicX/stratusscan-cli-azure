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

_DEFAULT_ROUTE_PREFIXES = {"0.0.0.0/0", "::/0"}


def collect_route_tables(subscription_id: str) -> list:
    client = utils.get_azure_client("network", subscription_id)
    log.info("Listing all route tables in subscription %s", subscription_id)
    return list(client.route_tables.list_all())


def _default_route_next_hop(routes) -> str:
    hops = [
        utils.s(r.next_hop_type) for r in routes
        if utils.s(r.address_prefix).strip() in _DEFAULT_ROUTE_PREFIXES
    ]
    return ", ".join(hops)


def _route_rows(rt, rg: str) -> list:
    return [
        {
            "Route Table": rt.name,
            "Resource Group": rg,
            "Route Name": route.name,
            "Address Prefix": utils.s(route.address_prefix),
            "Next Hop Type": utils.s(route.next_hop_type),
            "Next Hop IP": utils.s(route.next_hop_ip_address),
            "Provisioning State": utils.s(route.provisioning_state),
        }
        for route in (rt.routes or [])
    ]


def main(subscription_id: str, subscription_name: str) -> None:
    environment = utils.detect_environment()
    if not utils.is_service_available_in_environment("network", environment):
        sys.exit(0)

    tables = collect_route_tables(subscription_id)
    if not tables:
        print("No route tables found.")
        return

    rows = []
    route_rows = []
    for rt in tables:
        rg = utils.extract_resource_group(rt.id)
        tags = rt.tags or {}
        routes = rt.routes or []
        rows.append({
            "Name": rt.name,
            "Resource Group": rg,
            "Location": rt.location,
            "Route Count": len(routes),
            "Associated Subnets": len(rt.subnets or []),
            "Disable BGP Route Propagation": (
                "" if rt.disable_bgp_route_propagation is None else rt.disable_bgp_route_propagation
            ),
            "Provisioning State": utils.s(rt.provisioning_state),
            "Tags": "; ".join(f"{k}={v}" for k, v in tags.items()),
            "Default Route Next Hop": _default_route_next_hop(routes),
        })
        route_rows.extend(_route_rows(rt, rg))

    filename = utils.create_export_filename(subscription_name, "route-tables", "all")
    utils.save_multiple_dataframes_to_excel(
        {"Route Tables": pd.DataFrame(rows), "Routes": pd.DataFrame(route_rows)}, filename
    )
    print(f"Exported {len(rows)} route table(s) and {len(route_rows)} route(s) → {filename}")
    log.info("Export complete: %d route tables, %d routes", len(rows), len(route_rows))


if __name__ == "__main__":
    sub_id, sub_name = utils.resolve_target_subscription()
    if not sub_id:
        print("ERROR: No subscription configured. Run configure.py first.")
        sys.exit(1)
    main(sub_id, sub_name)
