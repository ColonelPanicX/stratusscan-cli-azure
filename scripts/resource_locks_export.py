#!/usr/bin/env python3
"""StratusScanCLI-Azure — Resource Locks Export"""

import sys
from pathlib import Path

try:
    import utils
except ImportError:
    sys.path.append(str(Path(__file__).parent.parent))
    import utils

import pandas as pd

utils.setup_logging("resource-locks-export")
utils.log_script_start("resource_locks_export.py", "Resource Locks Export")

log = utils.get_logger()


def collect_locks(subscription_id: str) -> list:
    client = utils.get_azure_client("locks", subscription_id)
    log.info("Listing all management locks in subscription %s", subscription_id)
    return list(client.management_locks.list_at_subscription_level())


def _scope(lock) -> str:
    lock_id = getattr(lock, "id", "") or ""
    marker = "/providers/Microsoft.Authorization/locks/"
    return lock_id.split(marker)[0] if marker in lock_id else lock_id


def _resource_group(scope: str) -> str:
    if "/resourceGroups/" in scope:
        return scope.split("/resourceGroups/")[1].split("/")[0]
    return ""


def _resource_name_and_type(scope: str) -> tuple:
    if "/providers/" not in scope:
        return "", ""
    tail = scope.split("/providers/", 1)[1]
    parts = tail.split("/")
    if len(parts) >= 3:
        ns = parts[0]
        rtype = parts[1]
        name = parts[-1]
        return name, f"{ns}/{rtype}"
    return "", ""


def main(subscription_id: str, subscription_name: str) -> None:
    environment = utils.detect_environment()
    if not utils.is_service_available_in_environment("locks", environment):
        sys.exit(0)

    locks = collect_locks(subscription_id)
    if not locks:
        print("No resource locks found.")
        return

    rows = []
    for lock in locks:
        scope = _scope(lock)
        res_name, res_type = _resource_name_and_type(scope)
        rows.append({
            "Lock Name": lock.name or "",
            "Resource Name": res_name,
            "Resource Type": res_type,
            "Resource Group": _resource_group(scope),
            "Lock Level": str(lock.level) if getattr(lock, "level", None) else "",
            "Notes": getattr(lock, "notes", "") or "",
            "Scope": scope,
        })

    df = pd.DataFrame(rows)
    filename = utils.create_export_filename(subscription_name, "resource-locks", "all")
    utils.save_dataframe_to_excel(df, filename, sheet_name="Resource Locks")
    print(f"Exported {len(rows)} resource lock(s) → {filename}")
    log.info("Export complete: %d locks", len(rows))


if __name__ == "__main__":
    cfg = utils.get_config()
    sub_id = cfg.get("default_subscription_id", "")
    sub_name = utils.get_subscription_name(sub_id)
    if not sub_id:
        print("ERROR: No subscription configured. Run configure.py first.")
        sys.exit(1)
    main(sub_id, sub_name)
