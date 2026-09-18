#!/usr/bin/env python3
"""StratusScanCLI-Azure — Management Groups Export"""

import sys
from pathlib import Path
from typing import Any

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


def _error_code(error: BaseException) -> str:
    code = getattr(getattr(error, "error", None), "code", None)
    if code:
        return utils.s(code)
    status = getattr(error, "status_code", None)
    if status:
        return f"HTTP {status}"
    return type(error).__name__


def _is_authorization_failed(error: HttpResponseError) -> bool:
    code = getattr(getattr(error, "error", None), "code", "") or ""
    return code == "AuthorizationFailed" or "AuthorizationFailed" in str(error)


def _count_subscriptions(mg) -> int:
    children = getattr(mg, "children", None) or []
    return sum(1 for child in children if utils.s(getattr(child, "type", None)).endswith("/subscriptions"))


def _get_parent_info(mg) -> tuple:
    details = getattr(mg, "details", None)
    parent = getattr(details, "parent", None) if details else None
    if not parent:
        return "", ""
    parent_id = utils.s(getattr(parent, "id", None))
    parent_name = utils.s(getattr(parent, "display_name", None)) or utils.s(getattr(parent, "name", None))
    if not parent_name and parent_id:
        parent_name = parent_id.split("/")[-1]
    return parent_id, parent_name


def _build_row(mg, detail: Any, detail_error: str) -> dict[str, Any]:
    source = detail if detail is not None else mg
    parent_id, parent_name = _get_parent_info(source)
    return {
        "Management Group Name": utils.s(mg.name),
        "Display Name": utils.s(getattr(source, "display_name", None)),
        "ID": utils.s(getattr(mg, "id", None)),
        "Tenant ID": utils.s(getattr(source, "tenant_id", None)),
        "Parent ID": parent_id,
        "Parent Name": parent_name,
        "Subscription Count": _count_subscriptions(detail) if detail is not None else "",
        "Detail Error": detail_error,
    }


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
        mg_id = utils.s(mg.name)
        detail = None
        detail_error = ""
        try:
            detail = client.management_groups.get(mg_id, expand="children")
        except Exception as e:
            detail_error = _error_code(e)
            log.warning("Failed to get details for management group %s: %s", mg_id, e)
        rows.append(_build_row(mg, detail, detail_error))

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
    sub_id, sub_name = utils.resolve_target_subscription()
    if not sub_id:
        print("ERROR: No subscription configured. Run configure.py first.")
        sys.exit(1)
    main(sub_name)
