#!/usr/bin/env python3
"""StratusScanCLI-Azure — Management Groups Export"""

import sys
from pathlib import Path

from azure.core.exceptions import HttpResponseError

try:
    import utils
except ImportError:
    sys.path.append(str(Path(__file__).parent.parent))
    import utils

import pandas as pd

utils.setup_logging("management-groups-export")
utils.log_script_start("management_groups_export.py", "Management Groups Export")

log = utils.get_logger()


def _is_authorization_failed(error: HttpResponseError) -> bool:
    code = getattr(getattr(error, "error", None), "code", "") or ""
    return code == "AuthorizationFailed" or "AuthorizationFailed" in str(error)


def _count_subscriptions(mg) -> int:
    if not hasattr(mg, "children") or not mg.children:
        return 0
    return sum(
        1 for child in mg.children
        if child.type and child.type.endswith("/subscriptions")
    )


def _get_parent_info(mg) -> tuple:
    if not hasattr(mg, "details") or not mg.details:
        return "", ""
    parent = getattr(mg.details, "parent", None)
    if not parent:
        return "", ""
    parent_id = getattr(parent, "id", "") or ""
    parent_name = getattr(parent, "display_name", "") or getattr(parent, "name", "") or ""
    if not parent_name and parent_id:
        parent_name = parent_id.split("/")[-1]
    return parent_id, parent_name


def collect_management_groups() -> list:
    client = utils.get_azure_client("managementgroups")
    log.info("Listing management groups")

    try:
        groups = list(client.management_groups.list())
    except HttpResponseError as e:
        if not _is_authorization_failed(e):
            raise
        log.warning(
            "Skipping management groups export: authenticated identity lacks "
            "Microsoft.Management/managementGroups/read permission"
        )
        sys.exit(0)

    log.info("Found %d management group(s), fetching details", len(groups))

    rows = []
    for mg in groups:
        mg_id = mg.name or ""
        try:
            detail = client.management_groups.get(mg_id, expand="children")
        except Exception as e:
            log.warning("Failed to get details for management group %s: %s", mg_id, e)
            detail = mg

        parent_id, parent_name = _get_parent_info(detail)
        sub_count = _count_subscriptions(detail)

        rows.append({
            "Management Group Name": getattr(detail, "display_name", "") or mg_id,
            "Display Name": getattr(detail, "display_name", "") or "",
            "ID": mg_id,
            "Parent ID": parent_id,
            "Parent Name": parent_name,
            "Subscription Count": sub_count,
        })

    return rows


def main(subscription_name: str) -> None:
    rows = collect_management_groups()

    if not rows:
        print("No management groups found.")
        return

    df = pd.DataFrame(rows)
    filename = utils.create_export_filename(subscription_name, "management-groups", "all")
    utils.save_dataframe_to_excel(df, filename)
    print(f"Exported {len(rows)} management group(s) → {filename}")
    log.info("Export complete: %d management groups", len(rows))


if __name__ == "__main__":
    cfg = utils.get_config()
    sub_id = cfg.get("default_subscription_id", "")
    sub_name = utils.get_subscription_name(sub_id)
    if not sub_id:
        print("ERROR: No subscription configured. Run configure.py first.")
        sys.exit(1)
    main(sub_name)
