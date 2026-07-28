#!/usr/bin/env python3
"""StratusScanCLI-Azure — Virtual Machines Export"""

import sys
from pathlib import Path

try:
    import utils
except ImportError:
    sys.path.append(str(Path(__file__).parent.parent))
    import utils

import pandas as pd

utils.setup_logging("virtual-machines-export")
utils.log_script_start("virtual_machines_export.py", "Azure Virtual Machines Export")

log = utils.get_logger()


def collect_vms(client) -> list:
    return list(client.virtual_machines.list_all())


def collect_power_states(client) -> dict:
    """Map lowercased VM resource id to power state via one status-scoped list call.

    `list_all()` alone never populates `instance_view`, so power state has to come
    from a second, status-only pass. The two calls are kept separate because the
    statusOnly payload is not guaranteed to carry the inventory properties
    (size, image, zones, tags) the export also needs.
    """
    states = {}
    try:
        for vm in client.virtual_machines.list_all(status_only="true"):
            state = _power_state_from_statuses(getattr(vm.instance_view, "statuses", None))
            if vm.id and state:
                states[vm.id.lower()] = state
    except Exception as e:
        log.warning("statusOnly VM listing failed (%s) — falling back to per-VM instance view", e)
    return states


def _power_state_from_statuses(statuses) -> str:
    if not statuses:
        return ""
    for s in statuses:
        code = getattr(s, "code", None)
        if code and code.startswith("PowerState/"):
            return code.replace("PowerState/", "")
    return ""


def _instance_view_power_state(client, resource_group: str, name: str) -> str:
    if not resource_group or not name:
        return ""
    try:
        view = client.virtual_machines.instance_view(resource_group, name)
        return _power_state_from_statuses(getattr(view, "statuses", None))
    except Exception as e:
        log.warning("Instance view failed for VM %s: %s", name, e)
        return ""


def _get_os_type(vm) -> str:
    try:
        profile = vm.storage_profile
        if profile and profile.os_disk and profile.os_disk.os_type:
            return str(profile.os_disk.os_type)
    except Exception:
        pass
    return ""


def _get_status(client, vm, states: dict, resource_group: str) -> str:
    state = states.get(vm.id.lower(), "") if vm.id else ""
    if not state:
        state = _instance_view_power_state(client, resource_group, vm.name)
    return state or "unknown"


def main(subscription_id: str, subscription_name: str) -> None:
    environment = utils.detect_environment()
    if not utils.is_service_available_in_environment("compute", environment):
        sys.exit(0)

    client = utils.get_azure_client("compute", subscription_id)
    log.info("Listing all VMs in subscription %s", subscription_id)
    vms = collect_vms(client)
    if not vms:
        print("No virtual machines found.")
        return

    states = collect_power_states(client)
    log.info("Resolved power state for %d of %d VMs from statusOnly listing", len(states), len(vms))

    rows = []
    for vm in vms:
        tags = vm.tags or {}
        rg = utils.extract_resource_group(vm.id)
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
            "Power State": _get_status(client, vm, states, rg),
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
    sub_id, sub_name = utils.resolve_target_subscription()
    if not sub_id:
        print("ERROR: No subscription configured. Run configure.py first.")
        sys.exit(1)
    main(sub_id, sub_name)
