#!/usr/bin/env python3
"""StratusScanCLI-Azure — Disk Snapshots Export"""

import sys
from pathlib import Path

try:
    import utils
except ImportError:
    sys.path.append(str(Path(__file__).parent.parent))
    import utils

import pandas as pd

utils.setup_logging("snapshots-export")
utils.log_script_start("snapshots_export.py", "Disk Snapshots Export")

log = utils.get_logger()


def collect_snapshots(subscription_id: str) -> list:
    client = utils.get_azure_client("compute", subscription_id)
    log.info("Listing all snapshots in subscription %s", subscription_id)
    return list(client.snapshots.list())


def collect_disk_ids(subscription_id: str) -> set:
    client = utils.get_azure_client("compute", subscription_id)
    return {disk.id.lower() for disk in client.disks.list() if disk.id}


def _source_disk_id(snapshot) -> str:
    try:
        return snapshot.creation_data.source_resource_id or ""
    except Exception:
        return ""


def main(subscription_id: str, subscription_name: str) -> None:
    environment = utils.detect_environment()
    if not utils.is_service_available_in_environment("compute", environment):
        sys.exit(0)

    snapshots = collect_snapshots(subscription_id)
    if not snapshots:
        print("No snapshots found.")
        return

    existing_disks = collect_disk_ids(subscription_id)

    rows = []
    for snap in snapshots:
        rg = snap.id.split("/resourceGroups/")[1].split("/")[0] if snap.id else ""
        source_id = _source_disk_id(snap)
        source_name = source_id.split("/")[-1] if source_id else ""
        source_rg = ""
        if "/resourceGroups/" in source_id:
            source_rg = source_id.split("/resourceGroups/")[1].split("/")[0]

        is_disk_source = "/disks/" in source_id.lower()
        if not source_id or not is_disk_source:
            orphaned = "N/A"
        else:
            orphaned = "No" if source_id.lower() in existing_disks else "Yes"

        tags = snap.tags or {}
        rows.append({
            "Name": snap.name,
            "Resource Group": rg,
            "Location": snap.location,
            "Source Disk": source_name,
            "Source Resource Group": source_rg,
            "OS Type": str(snap.os_type) if snap.os_type else "Data",
            "Disk Size GB": snap.disk_size_gb or "",
            "SKU": snap.sku.name if snap.sku else "",
            "Time Created": str(snap.time_created) if snap.time_created else "",
            "Incremental": "Yes" if snap.incremental else "No",
            "Orphaned": orphaned,
            "Provisioning State": snap.provisioning_state or "",
            "Tags": "; ".join(f"{k}={v}" for k, v in tags.items()),
        })

    df = pd.DataFrame(rows)
    filename = utils.create_export_filename(subscription_name, "snapshots", "all")
    utils.save_dataframe_to_excel(df, filename, sheet_name="Snapshots")
    print(f"Exported {len(rows)} snapshot(s) → {filename}")
    log.info("Export complete: %d snapshots", len(rows))


if __name__ == "__main__":
    cfg = utils.get_config()
    sub_id = cfg.get("default_subscription_id", "")
    sub_name = utils.get_subscription_name(sub_id)
    if not sub_id:
        print("ERROR: No subscription configured. Run configure.py first.")
        sys.exit(1)
    main(sub_id, sub_name)
