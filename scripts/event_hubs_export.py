#!/usr/bin/env python3
"""StratusScanCLI-Azure — Event Hubs Namespaces Export"""

import sys
from pathlib import Path

try:
    import utils
except ImportError:
    sys.path.append(str(Path(__file__).parent.parent))
    import utils

import pandas as pd

utils.setup_logging("event-hubs-export")
utils.log_script_start("event_hubs_export.py", "Event Hubs Namespaces Export")

log = utils.get_logger()


def collect_namespaces(subscription_id: str) -> list:
    client = utils.get_azure_client("eventhub", subscription_id)
    log.info("Listing Event Hubs namespaces in subscription %s", subscription_id)
    return list(client.namespaces.list_by_subscription())


def main(subscription_id: str, subscription_name: str) -> None:
    environment = utils.detect_environment()
    if not utils.is_service_available_in_environment("eventhub", environment):
        sys.exit(0)

    namespaces = collect_namespaces(subscription_id)
    if not namespaces:
        print("No Event Hubs namespaces found.")
        return

    rows = []
    for ns in namespaces:
        sku = ns.sku
        tags = ns.tags or {}
        rows.append({
            "Name": ns.name,
            "Resource Group": utils.extract_resource_group(ns.id),
            "Location": ns.location,
            "SKU": sku.name if sku else "",
            "Tier": str(sku.tier) if sku and getattr(sku, "tier", None) else "",
            "Capacity": getattr(sku, "capacity", "") if sku else "",
            "Provisioning State": ns.provisioning_state or "",
            "Auto-Inflate": "Yes" if getattr(ns, "is_auto_inflate_enabled", False) else "No",
            "Max Throughput Units": getattr(ns, "maximum_throughput_units", "") or "",
            "Kafka Enabled": "Yes" if getattr(ns, "kafka_enabled", False) else "No",
            "Zone Redundant": "Yes" if getattr(ns, "zone_redundant", False) else "No",
            "Endpoint": getattr(ns, "service_bus_endpoint", "") or "",
            "Tags": "; ".join(f"{k}={v}" for k, v in tags.items()),
        })

    df = pd.DataFrame(rows)
    filename = utils.create_export_filename(subscription_name, "event-hubs", "all")
    utils.save_dataframe_to_excel(df, filename, sheet_name="Event Hubs")
    print(f"Exported {len(rows)} Event Hubs namespace(s) → {filename}")
    log.info("Export complete: %d namespaces", len(rows))


if __name__ == "__main__":
    cfg = utils.get_config()
    sub_id = cfg.get("default_subscription_id", "")
    sub_name = utils.get_subscription_name(sub_id)
    if not sub_id:
        print("ERROR: No subscription configured. Run configure.py first.")
        sys.exit(1)
    main(sub_id, sub_name)
