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
    try:
        enc = disk.encryption
        if enc and enc.type:
            return str(enc.type)
    except Exception:
        pass
    return "PlatformManagedKey"


def _attached_vm(disk) -> str:
    try:
        if disk.managed_by:
            return disk.managed_by.split("/")[-1]
    except Exception:
        pass
    return ""


def main(subscription_id: str, subscription_name: str) -> None:
    environment = utils.detect_environment()
    if not utils.is_service_available_in_environment("compute", environment):
        sys.exit(0)

    disks = collect_disks(subscription_id)
    if not disks:
        print("No managed disks found.")
        return

    rows = []
    for disk in disks:
        rg = disk.id.split("/resourceGroups/")[1].split("/")[0] if disk.id else ""
        tags = disk.tags or {}
        rows.append({
            "Name": disk.name,
            "Resource Group": rg,
            "Location": disk.location,
            "Size (GiB)": disk.disk_size_gb or "",
            "SKU": disk.sku.name if disk.sku else "",
            "OS Type": str(disk.os_type) if disk.os_type else "Data",
            "State": str(disk.disk_state) if disk.disk_state else "",
            "Encryption": _encryption_type(disk),
            "Attached VM": _attached_vm(disk),
            "Orphaned": "Yes" if not disk.managed_by else "No",
            "Zones": ", ".join(disk.zones) if disk.zones else "",
            "Tags": "; ".join(f"{k}={v}" for k, v in tags.items()),
        })

    df = pd.DataFrame(rows)
    filename = utils.create_export_filename(subscription_name, "managed-disks", "all")
    utils.save_dataframe_to_excel(df, filename, sheet_name="Managed Disks")
    print(f"Exported {len(rows)} managed disk(s) → {filename}")
    log.info("Export complete: %d disks", len(rows))


if __name__ == "__main__":
    cfg = utils.get_config()
    sub_id = cfg.get("default_subscription_id", "")
    sub_name = utils.get_subscription_name(sub_id)
    if not sub_id:
        print("ERROR: No subscription configured. Run configure.py first.")
        sys.exit(1)
    main(sub_id, sub_name)
