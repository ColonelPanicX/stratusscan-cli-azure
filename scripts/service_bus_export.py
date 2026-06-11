#!/usr/bin/env python3
"""StratusScanCLI-Azure — Service Bus Namespaces Export"""

import sys
from pathlib import Path

try:
    import utils
except ImportError:
    sys.path.append(str(Path(__file__).parent.parent))
    import utils

import pandas as pd

utils.setup_logging("service-bus-export")
utils.log_script_start("service_bus_export.py", "Service Bus Namespaces Export")

log = utils.get_logger()


def collect_namespaces(subscription_id: str) -> list:
    client = utils.get_azure_client("servicebus", subscription_id)
    log.info("Listing Service Bus namespaces in subscription %s", subscription_id)
    return list(client.namespaces.list())


def main(subscription_id: str, subscription_name: str) -> None:
    environment = utils.detect_environment()
    if not utils.is_service_available_in_environment("servicebus", environment):
        sys.exit(0)

    namespaces = collect_namespaces(subscription_id)
    if not namespaces:
        print("No Service Bus namespaces found.")
        return

    rows = []
    for ns in namespaces:
        sku = ns.sku
        tags = ns.tags or {}
        rows.append({
            "Name": ns.name,
            "Resource Group": utils.extract_resource_group(ns.id),
            "Location": ns.location,
            "SKU": str(sku.name) if sku else "",
            "Tier": str(sku.tier) if sku and getattr(sku, "tier", None) else "",
            "Capacity": getattr(sku, "capacity", "") if sku else "",
            "Status": str(ns.status) if ns.status else "",
            "Provisioning State": ns.provisioning_state or "",
            "Zone Redundant": "Yes" if getattr(ns, "zone_redundant", False) else "No",
            "Endpoint": getattr(ns, "service_bus_endpoint", "") or "",
            "Tags": "; ".join(f"{k}={v}" for k, v in tags.items()),
        })

    df = pd.DataFrame(rows)
    filename = utils.create_export_filename(subscription_name, "service-bus", "all")
    utils.save_dataframe_to_excel(df, filename, sheet_name="Service Bus")
    print(f"Exported {len(rows)} Service Bus namespace(s) → {filename}")
    log.info("Export complete: %d namespaces", len(rows))


if __name__ == "__main__":
    cfg = utils.get_config()
    sub_id = cfg.get("default_subscription_id", "")
    sub_name = utils.get_subscription_name(sub_id)
    if not sub_id:
        print("ERROR: No subscription configured. Run configure.py first.")
        sys.exit(1)
    main(sub_id, sub_name)
