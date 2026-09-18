#!/usr/bin/env python3
"""StratusScanCLI-Azure — RBAC Role Definitions Export

Every role definition visible at subscription scope, split into a Custom Roles
sheet and a Built-In Roles sheet. The built-ins are the reference an auditor
reads the role-assignments export against, so both are exported in one pass and
the split is made client-side from role_type — one list call instead of two.

Permission lists are joined into a single cell and truncated at Excel's
32,767-character limit; a truncated cell ends with a marker that says so.
"""

import sys
from pathlib import Path
from typing import Any

try:
    import utils
except ImportError:
    sys.path.append(str(Path(__file__).parent.parent))
    import utils

import pandas as pd

log = utils.get_logger()

CELL_CHARACTER_LIMIT = 32767
TRUNCATION_MARKER = " …[truncated]"

CUSTOM_ROLE_TYPE = "customrole"

COLUMNS = [
    "Name", "Role ID", "Type", "Description", "Assignable Scopes",
    "Actions", "NotActions", "DataActions", "NotDataActions",
    "Created On", "Updated On", "Created By",
]


def collect_role_definitions(subscription_id: str) -> list:
    client = utils.get_azure_client("authorization", subscription_id)
    scope = f"/subscriptions/{subscription_id}"
    log.info("Listing role definitions visible at %s", scope)
    return list(client.role_definitions.list(scope=scope))


def _iso(value: Any) -> str:
    return value.strftime("%Y-%m-%d %H:%M:%S") if hasattr(value, "strftime") else utils.s(value)


def _fit_cell(text: str) -> str:
    if len(text) <= CELL_CHARACTER_LIMIT:
        return text
    return text[: CELL_CHARACTER_LIMIT - len(TRUNCATION_MARKER)] + TRUNCATION_MARKER


def _joined_permissions(role, attribute: str) -> str:
    values = []
    for permission in getattr(role, "permissions", None) or []:
        values.extend(utils.s(v) for v in (getattr(permission, attribute, None) or []))
    return _fit_cell(", ".join(values))


def _build_row(role) -> dict[str, Any]:
    scopes = getattr(role, "assignable_scopes", None) or []
    return {
        "Name": utils.s(getattr(role, "role_name", None)),
        "Role ID": utils.s(getattr(role, "name", None)),
        "Type": utils.s(getattr(role, "role_type", None)),
        "Description": utils.s(getattr(role, "description", None)),
        "Assignable Scopes": _fit_cell(", ".join(utils.s(s) for s in scopes)),
        "Actions": _joined_permissions(role, "actions"),
        "NotActions": _joined_permissions(role, "not_actions"),
        "DataActions": _joined_permissions(role, "data_actions"),
        "NotDataActions": _joined_permissions(role, "not_data_actions"),
        "Created On": _iso(getattr(role, "created_on", None)),
        "Updated On": _iso(getattr(role, "updated_on", None)),
        "Created By": utils.s(getattr(role, "created_by", None)),
    }


def split_rows(definitions: list) -> tuple[list, list]:
    """Return (custom rows, built-in rows) — role_type is 'CustomRole' or 'BuiltInRole'."""
    custom, builtin = [], []
    for role in definitions:
        row = _build_row(role)
        target = custom if row["Type"].lower() == CUSTOM_ROLE_TYPE else builtin
        target.append(row)
    return custom, builtin


def main(subscription_id: str, subscription_name: str) -> utils.ExportResult:
    environment = utils.detect_environment()
    if not utils.is_service_available_in_environment("authorization", environment):
        sys.exit(0)

    definitions = collect_role_definitions(subscription_id)
    if not definitions:
        raise utils.NoResourcesFound("role definitions")

    custom_rows, builtin_rows = split_rows(definitions)

    sheets = {
        "Custom Roles": pd.DataFrame(custom_rows, columns=COLUMNS),
        "Built-In Roles": pd.DataFrame(builtin_rows, columns=COLUMNS),
    }
    filename = utils.create_export_filename(subscription_name, "role-definitions", "all")
    utils.save_multiple_dataframes_to_excel(sheets, filename)
    print(
        f"Exported {len(custom_rows)} custom and {len(builtin_rows)} built-in "
        f"role definition(s) → {filename}"
    )
    log.info(
        "Export complete: %d custom, %d built-in role definitions",
        len(custom_rows), len(builtin_rows),
    )
    return utils.ExportResult(rows=len(definitions), filename=filename, errors=[])


if __name__ == "__main__":
    import runner

    runner.run_exporter(main, "role-definitions")
