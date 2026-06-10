#!/usr/bin/env python3
"""StratusScanCLI-Azure — Availability Sets Export"""

import sys
from pathlib import Path

try:
    import utils
except ImportError:
    sys.path.append(str(Path(__file__).parent.parent))
    import utils

import pandas as pd

utils.setup_logging("availability-sets-export")
utils.log_script_start("availability_sets_export.py", "Availability Sets Export")

log = utils.get_logger()


def collect_availability_sets(subscription_id: str) -> list:
    client = utils.get_azure_client("compute", subscription_id)
    log.info("Listing all availability sets in subscription %s", subscription_id)
    return list(client.availability_sets.list_by_subscription())


def _member_vms(avset) -> list:
    try:
        return [vm.id.split("/")[-1] for vm in (avset.virtual_machines or []) if vm.id]
    except Exception:
        return []


def _proximity_placement_group(avset) -> str:
    try:
        if avset.proximity_placement_group and avset.proximity_placement_group.id:
            return avset.proximity_placement_group.id.split("/")[-1]
    except Exception:
        pass
    return ""


def main(subscription_id: str, subscription_name: str) -> None:
    environment = utils.detect_environment()
    if not utils.is_service_available_in_environment("compute", environment):
        sys.exit(0)

    avsets = collect_availability_sets(subscription_id)
    if not avsets:
        print("No availability sets found.")
        return

    rows = []
    for avset in avsets:
        rg = avset.id.split("/resourceGroups/")[1].split("/")[0] if avset.id else ""
        vms = _member_vms(avset)
        tags = avset.tags or {}
        rows.append({
            "Name": avset.name,
            "Resource Group": rg,
            "Location": avset.location,
            "Fault Domain Count": avset.platform_fault_domain_count if avset.platform_fault_domain_count is not None else "",
            "Update Domain Count": avset.platform_update_domain_count if avset.platform_update_domain_count is not None else "",
            "SKU": avset.sku.name if avset.sku else "",
            "VM Count": len(vms),
            "VMs": ", ".join(vms),
            "Proximity Placement Group": _proximity_placement_group(avset),
            "Tags": "; ".join(f"{k}={v}" for k, v in tags.items()),
        })

    df = pd.DataFrame(rows)
    filename = utils.create_export_filename(subscription_name, "availability-sets", "all")
    utils.save_dataframe_to_excel(df, filename, sheet_name="Availability Sets")
    print(f"Exported {len(rows)} availability set(s) → {filename}")
    log.info("Export complete: %d availability sets", len(rows))


if __name__ == "__main__":
    cfg = utils.get_config()
    sub_id = cfg.get("default_subscription_id", "")
    sub_name = utils.get_subscription_name(sub_id)
    if not sub_id:
        print("ERROR: No subscription configured. Run configure.py first.")
        sys.exit(1)
    main(sub_id, sub_name)
