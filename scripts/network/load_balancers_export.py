#!/usr/bin/env python3
"""StratusScanCLI-Azure — Load Balancers Export"""

import sys
from pathlib import Path

try:
    import utils
except ImportError:
    sys.path.append(str(Path(__file__).parent.parent.parent))
    import utils

import pandas as pd

utils.setup_logging("load-balancers-export")
utils.log_script_start("load_balancers_export.py", "Azure Load Balancers Export")

log = utils.get_logger()


def collect_load_balancers(subscription_id: str) -> list:
    client = utils.get_azure_client("network", subscription_id)
    log.info("Listing all load balancers in subscription %s", subscription_id)
    return list(client.load_balancers.list_all())


def main(subscription_id: str, subscription_name: str) -> None:
    environment = utils.detect_environment()
    if not utils.is_service_available_in_environment("network", environment):
        sys.exit(0)

    lbs = collect_load_balancers(subscription_id)
    if not lbs:
        print("No load balancers found.")
        return

    rows = []
    for lb in lbs:
        rg = lb.id.split("/resourceGroups/")[1].split("/")[0] if lb.id else ""
        tags = lb.tags or {}
        frontend_ips = len(lb.frontend_ip_configurations or [])
        backend_pools = len(lb.backend_address_pools or [])
        lb_rules = len(lb.load_balancing_rules or [])
        probes = len(lb.probes or [])
        rows.append({
            "Name": lb.name,
            "Resource Group": rg,
            "Location": lb.location,
            "SKU": lb.sku.name if lb.sku else "",
            "Frontend IPs": frontend_ips,
            "Backend Pools": backend_pools,
            "Load Balancing Rules": lb_rules,
            "Probes": probes,
            "Provisioning State": lb.provisioning_state or "",
            "Tags": "; ".join(f"{k}={v}" for k, v in tags.items()),
        })

    df = pd.DataFrame(rows)
    filename = utils.create_export_filename(subscription_name, "load-balancers", "all")
    utils.save_dataframe_to_excel(df, filename, sheet_name="Load Balancers")
    print(f"Exported {len(rows)} load balancer(s) → {filename}")
    log.info("Export complete: %d load balancers", len(rows))


if __name__ == "__main__":
    cfg = utils.get_config()
    sub_id = cfg.get("default_subscription_id", "")
    sub_name = utils.get_subscription_name(sub_id)
    if not sub_id:
        print("ERROR: No subscription configured. Run configure.py first.")
        sys.exit(1)
    main(sub_id, sub_name)
