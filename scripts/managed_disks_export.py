#!/usr/bin/env python3
"""StratusScanCLI-Azure — Managed Disks Export"""

import sys
from pathlib import Path

try:
    import utils
except ImportError:
    sys.path.append(str(Path(__file__).parent.parent))
    import utils

import pandas as pd

utils.setup_logging("managed-disks-export")
utils.log_script_start("managed_disks_export.py", "Azure Managed Disks Export")

log = utils.get_logger()


def collect_disks(subscription_id: str) -> list:
    client = utils.get_azure_client("compute", subscription_id)
    log.info("Listing all managed disks in subscription %s", subscription_id)
    return list(client.disks.list())


def _encryption_type(disk) -> str:
    enc = disk.encryption
    return utils.s(enc.type) if enc else ""


def _disk_encryption_set(disk) -> str:
    enc = disk.encryption
    des_id = enc.disk_encryption_set_id if enc else None
    return des_id.split("/")[-1] if des_id else ""


def _attached_vm(disk) -> str:
    return disk.managed_by.split("/")[-1] if disk.managed_by else ""


def _orphaned(disk) -> str:
    state = utils.s(disk.disk_state)
    if state:
        return "Yes" if state.lower() == "unattached" else "No"
    return "Yes" if not disk.managed_by else "No"


def _build_row(disk) -> dict:
    tags = disk.tags or {}
    return {
        "Name": disk.name,
        "Resource Group": utils.extract_resource_group(disk.id),
        "Location": disk.location,
        "Size (GiB)": disk.disk_size_gb if disk.disk_size_gb is not None else "",
        "SKU": utils.s(disk.sku.name) if disk.sku else "",
        "OS Type": utils.s(disk.os_type) if disk.os_type else "Data",
        "State": utils.s(disk.disk_state),
        "Encryption": _encryption_type(disk),
        "Attached VM": _attached_vm(disk),
        "Orphaned": _orphaned(disk),
        "Zones": ", ".join(disk.zones) if disk.zones else "",
        "Tags": "; ".join(f"{k}={v}" for k, v in tags.items()),
        "Disk Encryption Set": _disk_encryption_set(disk),
        "Network Access Policy": utils.s(disk.network_access_policy),
        "Public Network Access": utils.s(disk.public_network_access),
    }


def main(subscription_id: str, subscription_name: str) -> utils.ExportResult:
    environment = utils.detect_environment()
    if not utils.is_service_available_in_environment("compute", environment):
        sys.exit(0)

    disks = collect_disks(subscription_id)
    if not disks:
        raise utils.NoResourcesFound("managed disks")

    rows = [_build_row(disk) for disk in disks]

    df = pd.DataFrame(rows)
    filename = utils.create_export_filename(subscription_name, "managed-disks", "all")
    utils.save_dataframe_to_excel(df, filename, sheet_name="Managed Disks")
    print(f"Exported {len(rows)} managed disk(s) → {filename}")
    log.info("Export complete: %d disks", len(rows))
    return utils.ExportResult(rows=len(rows), filename=filename, errors=[])


if __name__ == "__main__":
    import runner

    runner.run_exporter(main, "managed-disks")
