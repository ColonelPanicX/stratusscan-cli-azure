#!/usr/bin/env python3
"""StratusScanCLI-Azure — Traffic Manager Profiles Export"""

import sys
from pathlib import Path

try:
    import utils
except ImportError:
    sys.path.append(str(Path(__file__).parent.parent))
    import utils

import pandas as pd

utils.setup_logging("traffic-manager-export")
utils.log_script_start("traffic_manager_export.py", "Traffic Manager Profiles Export")

log = utils.get_logger()


def collect_profiles(subscription_id: str) -> list:
    client = utils.get_azure_client("trafficmanager", subscription_id)
    log.info("Listing Traffic Manager profiles in subscription %s", subscription_id)
    return list(client.profiles.list_by_subscription())


def main(subscription_id: str, subscription_name: str) -> None:
    environment = utils.detect_environment()
    if not utils.is_service_available_in_environment("trafficmanager", environment):
        sys.exit(0)

    profiles = collect_profiles(subscription_id)
    if not profiles:
        print("No Traffic Manager profiles found.")
        return

    rows = []
    for prof in profiles:
        dns = prof.dns_config
        monitor = prof.monitor_config
        tags = prof.tags or {}
        rows.append({
            "Name": prof.name,
            "Resource Group": utils.extract_resource_group(prof.id),
            "Status": str(prof.profile_status) if prof.profile_status else "",
            "Routing Method": str(prof.traffic_routing_method) if prof.traffic_routing_method else "",
            "FQDN": getattr(dns, "fqdn", "") if dns else "",
            "TTL": getattr(dns, "ttl", "") if dns else "",
            "Monitor Protocol": str(getattr(monitor, "protocol", "")) if monitor else "",
            "Monitor Port": getattr(monitor, "port", "") if monitor else "",
            "Monitor Path": getattr(monitor, "path", "") if monitor else "",
            "Endpoint Count": len(prof.endpoints or []),
            "Tags": "; ".join(f"{k}={v}" for k, v in tags.items()),
        })

    df = pd.DataFrame(rows)
    filename = utils.create_export_filename(subscription_name, "traffic-manager", "all")
    utils.save_dataframe_to_excel(df, filename, sheet_name="Traffic Manager")
    print(f"Exported {len(rows)} Traffic Manager profile(s) → {filename}")
    log.info("Export complete: %d profiles", len(rows))


if __name__ == "__main__":
    sub_id, sub_name = utils.resolve_target_subscription()
    if not sub_id:
        print("ERROR: No subscription configured. Run configure.py first.")
        sys.exit(1)
    main(sub_id, sub_name)
