#!/usr/bin/env python3
"""StratusScanCLI-Azure — Virtual Machines Export"""

import sys
from pathlib import Path

try:
    import utils
except ImportError:
    sys.path.append(str(Path(__file__).parent.parent.parent))
    import utils

import pandas as pd

utils.setup_logging("virtual-machines-export")
utils.log_script_start("virtual_machines_export.py", "Azure Virtual Machines Export")

log = utils.get_logger()


def collect_vms(subscription_id: str) -> list:
    client = utils.get_azure_client("compute", subscription_id)
    log.info("Listing all VMs in subscription %s", subscription_id)
    return list(client.virtual_machines.list_all())


def _get_os_type(vm) -> str:
    try:
        profile = vm.storage_profile
        if profile and profile.os_disk and profile.os_disk.os_type:
            return str(profile.os_disk.os_type)
    except Exception:
        pass
    return ""


def _get_status(vm) -> str:
    try:
        if vm.instance_view and vm.instance_view.statuses:
            for s in vm.instance_view.statuses:
                if s.code and s.code.startswith("PowerState/"):
                    return s.code.replace("PowerState/", "")
    except Exception:
        pass
    return "unknown"


def main(subscription_id: str, subscription_name: str) -> None:
    environment = utils.detect_environment()
    if not utils.is_service_available_in_environment("compute", environment):
        sys.exit(0)

    vms = collect_vms(subscription_id)
    if not vms:
        print("No virtual machines found.")
        return

    rows = []
    for vm in vms:
        tags = vm.tags or {}
        rg = vm.id.split("/resourceGroups/")[1].split("/")[0] if vm.id else ""
        rows.append({
            "Name": vm.name,
            "Resource Group": rg,
            "Location": vm.location,
            "VM Size": vm.hardware_profile.vm_size if vm.hardware_profile else "",
            "OS Type": _get_os_type(vm),
            "OS Image": (
                f"{vm.storage_profile.image_reference.publisher}/"
                f"{vm.storage_profile.image_reference.offer}/"
                f"{vm.storage_profile.image_reference.sku}"
                if vm.storage_profile and vm.storage_profile.image_reference
                and vm.storage_profile.image_reference.publisher
                else ""
            ),
            "Power State": _get_status(vm),
            "Provisioning State": vm.provisioning_state or "",
            "Zones": ", ".join(vm.zones) if vm.zones else "",
            "Tags": "; ".join(f"{k}={v}" for k, v in tags.items()),
        })

    df = pd.DataFrame(rows)
    filename = utils.create_export_filename(subscription_name, "virtual-machines", "all")
    utils.save_dataframe_to_excel(df, filename, sheet_name="Virtual Machines")
    print(f"Exported {len(rows)} virtual machine(s) → {filename}")
    log.info("Export complete: %d VMs", len(rows))


if __name__ == "__main__":
    cfg = utils.get_config()
    sub_id = cfg.get("default_subscription_id", "")
    sub_name = utils.get_subscription_name(sub_id)
    if not sub_id:
        print("ERROR: No subscription configured. Run configure.py first.")
        sys.exit(1)
    main(sub_id, sub_name)
