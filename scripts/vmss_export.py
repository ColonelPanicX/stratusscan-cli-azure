#!/usr/bin/env python3
"""StratusScanCLI-Azure — Virtual Machine Scale Sets Export"""

import sys
from pathlib import Path

try:
    import utils
except ImportError:
    sys.path.append(str(Path(__file__).parent.parent))
    import utils

import pandas as pd

utils.setup_logging("vmss-export")
utils.log_script_start("vmss_export.py", "Virtual Machine Scale Sets Export")

log = utils.get_logger()


def collect_scale_sets(subscription_id: str) -> list:
    client = utils.get_azure_client("compute", subscription_id)
    log.info("Listing all VM scale sets in subscription %s", subscription_id)
    return list(client.virtual_machine_scale_sets.list_all())


def _os_type(vmss) -> str:
    try:
        profile = vmss.virtual_machine_profile
        os_disk = profile.storage_profile.os_disk
        if os_disk and os_disk.os_type:
            return str(os_disk.os_type)
    except Exception:
        pass
    return ""


def _admin_username(vmss) -> str:
    try:
        return vmss.virtual_machine_profile.os_profile.admin_username or ""
    except Exception:
        return ""


def _upgrade_policy(vmss) -> str:
    try:
        if vmss.upgrade_policy and vmss.upgrade_policy.mode:
            return str(vmss.upgrade_policy.mode)
    except Exception:
        pass
    return ""


def main(subscription_id: str, subscription_name: str) -> None:
    environment = utils.detect_environment()
    if not utils.is_service_available_in_environment("compute", environment):
        sys.exit(0)

    scale_sets = collect_scale_sets(subscription_id)
    if not scale_sets:
        print("No VM scale sets found.")
        return

    rows = []
    for vmss in scale_sets:
        rg = vmss.id.split("/resourceGroups/")[1].split("/")[0] if vmss.id else ""
        tags = vmss.tags or {}
        rows.append({
            "Name": vmss.name,
            "Resource Group": rg,
            "Location": vmss.location,
            "SKU Name": vmss.sku.name if vmss.sku else "",
            "SKU Capacity": vmss.sku.capacity if vmss.sku else "",
            "Upgrade Policy": _upgrade_policy(vmss),
            "Orchestration Mode": str(vmss.orchestration_mode) if vmss.orchestration_mode else "",
            "OS Type": _os_type(vmss),
            "Admin Username": _admin_username(vmss),
            "Provisioning State": vmss.provisioning_state or "",
            "Overprovision": "Yes" if vmss.overprovision else "No",
            "Tags": "; ".join(f"{k}={v}" for k, v in tags.items()),
        })

    df = pd.DataFrame(rows)
    filename = utils.create_export_filename(subscription_name, "vmss", "all")
    utils.save_dataframe_to_excel(df, filename, sheet_name="VM Scale Sets")
    print(f"Exported {len(rows)} VM scale set(s) → {filename}")
    log.info("Export complete: %d scale sets", len(rows))


if __name__ == "__main__":
    cfg = utils.get_config()
    sub_id = cfg.get("default_subscription_id", "")
    sub_name = utils.get_subscription_name(sub_id)
    if not sub_id:
        print("ERROR: No subscription configured. Run configure.py first.")
        sys.exit(1)
    main(sub_id, sub_name)
