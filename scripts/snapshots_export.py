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

log = utils.get_logger()


def collect_snapshots(subscription_id: str) -> list:
    client = utils.get_azure_client("compute", subscription_id)
    log.info("Listing all snapshots in subscription %s", subscription_id)
    return list(client.snapshots.list())


def collect_disk_ids(subscription_id: str) -> set:
    client = utils.get_azure_client("compute", subscription_id)
    return {disk.id.lower() for disk in client.disks.list() if disk.id}


def _source_disk_id(snapshot) -> str:
    creation = snapshot.creation_data
    return (creation.source_resource_id if creation else None) or ""


def _subscription_of(resource_id: str) -> str:
    parts = resource_id.split("/")
    for i, part in enumerate(parts):
        if part.lower() == "subscriptions" and i + 1 < len(parts):
            return parts[i + 1]
    return ""


def _orphaned(source_id: str, subscription_id: str, existing_disks: set) -> str:
    if not source_id or "/disks/" not in source_id.lower():
        return "N/A"
    if _subscription_of(source_id).lower() != subscription_id.lower():
        return "N/A (other subscription)"
    return "No" if source_id.lower() in existing_disks else "Yes"


def _build_row(snap, subscription_id: str, existing_disks: set) -> dict:
    tags = snap.tags or {}
    source_id = _source_disk_id(snap)
    encryption = snap.encryption
    return {
        "Name": snap.name,
        "Resource Group": utils.extract_resource_group(snap.id),
        "Location": snap.location,
        "Source Disk": source_id.split("/")[-1] if source_id else "",
        "Source Resource Group": utils.extract_resource_group(source_id),
        "OS Type": utils.s(snap.os_type) if snap.os_type else "Data",
        "Disk Size GB": snap.disk_size_gb if snap.disk_size_gb is not None else "",
        "SKU": utils.s(snap.sku.name) if snap.sku else "",
        "Time Created": utils.s(snap.time_created),
        "Incremental": "Yes" if snap.incremental else "No",
        "Orphaned": _orphaned(source_id, subscription_id, existing_disks),
        "Provisioning State": utils.s(snap.provisioning_state),
        "Tags": "; ".join(f"{k}={v}" for k, v in tags.items()),
        "Source Subscription": _subscription_of(source_id),
        "Encryption": utils.s(encryption.type) if encryption else "",
        "Network Access Policy": utils.s(snap.network_access_policy),
        "Public Network Access": utils.s(snap.public_network_access),
    }


def main(subscription_id: str, subscription_name: str) -> utils.ExportResult:
    environment = utils.detect_environment()
    if not utils.is_service_available_in_environment("compute", environment):
        sys.exit(0)

    snapshots = collect_snapshots(subscription_id)
    if not snapshots:
        raise utils.NoResourcesFound("snapshots")

    existing_disks = collect_disk_ids(subscription_id)
    rows = [_build_row(snap, subscription_id, existing_disks) for snap in snapshots]

    df = pd.DataFrame(rows)
    filename = utils.create_export_filename(subscription_name, "snapshots", "all")
    utils.save_dataframe_to_excel(df, filename, sheet_name="Snapshots")
    print(f"Exported {len(rows)} snapshot(s) → {filename}")
    log.info("Export complete: %d snapshots", len(rows))
    return utils.ExportResult(rows=len(rows), filename=filename, errors=[])


if __name__ == "__main__":
    import runner

    runner.run_exporter(main, "snapshots")
