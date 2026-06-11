#!/usr/bin/env python3
"""StratusScanCLI-Azure — Container Instances (ACI) Export"""

import sys
from pathlib import Path

try:
    import utils
except ImportError:
    sys.path.append(str(Path(__file__).parent.parent))
    import utils

import pandas as pd

utils.setup_logging("container-instances-export")
utils.log_script_start("container_instances_export.py", "Container Instances (ACI) Export")

log = utils.get_logger()


def collect_groups(subscription_id: str) -> list:
    client = utils.get_azure_client("containerinstance", subscription_id)
    log.info("Listing container groups in subscription %s", subscription_id)
    return list(client.container_groups.list())


def _images(group) -> str:
    try:
        return ", ".join(c.image for c in (group.containers or []) if getattr(c, "image", None))
    except Exception:
        return ""


def _total_resources(group) -> str:
    try:
        cpu = 0.0
        mem = 0.0
        for c in group.containers or []:
            req = c.resources.requests
            cpu += req.cpu or 0
            mem += req.memory_in_gb or 0
        return f"{cpu} vCPU / {mem} GB"
    except Exception:
        return ""


def main(subscription_id: str, subscription_name: str) -> None:
    environment = utils.detect_environment()
    if not utils.is_service_available_in_environment("containerinstance", environment):
        sys.exit(0)

    groups = collect_groups(subscription_id)
    if not groups:
        print("No container groups found.")
        return

    rows = []
    for group in groups:
        ip = group.ip_address
        tags = group.tags or {}
        rows.append({
            "Name": group.name,
            "Resource Group": utils.extract_resource_group(group.id),
            "Location": group.location,
            "OS Type": str(group.os_type) if group.os_type else "",
            "Restart Policy": str(group.restart_policy) if group.restart_policy else "",
            "Provisioning State": str(group.provisioning_state) if group.provisioning_state else "",
            "IP Address": getattr(ip, "ip", "") if ip else "",
            "IP Type": str(getattr(ip, "type", "")) if ip else "",
            "FQDN": getattr(ip, "fqdn", "") if ip else "",
            "Container Count": len(group.containers or []),
            "Images": _images(group),
            "Total Requested": _total_resources(group),
            "Tags": "; ".join(f"{k}={v}" for k, v in tags.items()),
        })

    df = pd.DataFrame(rows)
    filename = utils.create_export_filename(subscription_name, "container-instances", "all")
    utils.save_dataframe_to_excel(df, filename, sheet_name="Container Instances")
    print(f"Exported {len(rows)} container group(s) → {filename}")
    log.info("Export complete: %d container groups", len(rows))


if __name__ == "__main__":
    sub_id, sub_name = utils.resolve_target_subscription()
    if not sub_id:
        print("ERROR: No subscription configured. Run configure.py first.")
        sys.exit(1)
    main(sub_id, sub_name)
