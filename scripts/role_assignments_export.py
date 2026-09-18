#!/usr/bin/env python3
"""StratusScanCLI-Azure — RBAC Role Assignments Export

Covers active Azure RBAC role assignments visible at subscription scope,
including those inherited from management groups and the tenant root.
Not covered: PIM-eligible assignments, classic administrators, deny assignments.
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
from azure.core.exceptions import HttpResponseError

utils.setup_logging("role-assignments-export")
utils.log_script_start("role_assignments_export.py", "Azure RBAC Role Assignments Export")

log = utils.get_logger()

_MANAGEMENT_GROUP_PREFIX = "/providers/microsoft.management/managementgroups/"


def collect_role_assignments(subscription_id: str) -> list:
    client = utils.get_azure_client("authorization", subscription_id)
    scope = f"/subscriptions/{subscription_id}"
    log.info("Listing role assignments for subscription %s", subscription_id)
    return list(client.role_assignments.list_for_scope(scope))


def collect_role_definitions(subscription_id: str) -> tuple:
    """Return ({role definition GUID (lowercase): RoleDefinition}, errors) for definitions visible at subscription scope."""
    client = utils.get_azure_client("authorization", subscription_id)
    scope = f"/subscriptions/{subscription_id}"
    log.info("Listing role definitions for subscription %s", subscription_id)
    errors: list = []
    try:
        definitions = {
            utils.s(rd.name).lower(): rd
            for rd in client.role_definitions.list(scope=scope)
            if getattr(rd, "name", None)
        }
    except HttpResponseError as e:
        errors.append(utils.error_record(scope, "role_definitions.list", e))
        log.warning("Failed to list role definitions — Role Name/Role Type will be blank: %s", e)
        definitions = {}
    return definitions, errors


def _role_name_from_id(role_definition_id: str) -> str:
    """Extract the role definition GUID from the full resource ID."""
    try:
        return role_definition_id.split("/")[-1]
    except Exception:
        return role_definition_id or ""


def _scope_type(scope: str) -> str:
    """Classify an assignment scope as tenant root / management group / subscription / resource group / resource."""
    if not scope:
        return ""
    if scope.strip() == "/":
        return "Root (Tenant)"
    if scope.lower().startswith(_MANAGEMENT_GROUP_PREFIX):
        return "Management Group"
    parts = scope.strip("/").split("/")
    if len(parts) == 2 and parts[0].lower() == "subscriptions":
        return "Subscription"
    if len(parts) == 4 and parts[0].lower() == "subscriptions" and parts[2].lower() == "resourcegroups":
        return "Resource Group"
    return "Resource"


def _iso(value: Any) -> str:
    return value.strftime("%Y-%m-%d %H:%M:%S") if hasattr(value, "strftime") else utils.s(value)


def _build_row(ra, role_definitions: dict[str, Any]) -> dict[str, Any]:
    role_guid = _role_name_from_id(utils.s(ra.role_definition_id))
    role = role_definitions.get(role_guid.lower())
    return {
        "Assignment ID": utils.s(ra.name),
        "Principal ID": utils.s(ra.principal_id),
        "Principal Type": utils.s(ra.principal_type),
        "Role Definition ID": role_guid,
        "Role Name": utils.s(getattr(role, "role_name", None)),
        "Role Type": utils.s(getattr(role, "role_type", None)),
        "Scope": utils.s(ra.scope),
        "Scope Type": _scope_type(utils.s(ra.scope)),
        "Created On": _iso(ra.created_on),
        "Condition": utils.s(getattr(ra, "condition", None)),
        "Description": utils.s(getattr(ra, "description", None)),
        "Created By": utils.s(getattr(ra, "created_by", None)),
        "Updated On": _iso(getattr(ra, "updated_on", None)),
    }


def main(subscription_id: str, subscription_name: str) -> utils.ExportResult:
    environment = utils.detect_environment()
    if not utils.is_service_available_in_environment("authorization", environment):
        sys.exit(0)

    assignments = collect_role_assignments(subscription_id)
    if not assignments:
        raise utils.NoResourcesFound("role assignments")

    role_definitions, errors = collect_role_definitions(subscription_id)
    rows = [_build_row(ra, role_definitions) for ra in assignments]

    df = pd.DataFrame(rows)
    filename = utils.create_export_filename(subscription_name, "role-assignments", "all")
    utils.save_dataframe_to_excel(df, filename, sheet_name="Role Assignments", errors=errors)
    print(f"Exported {len(rows)} role assignment(s) → {filename}")
    log.info("Export complete: %d role assignments", len(rows))
    return utils.ExportResult(rows=len(rows), filename=filename, errors=errors)


if __name__ == "__main__":
    import runner

    runner.run_exporter(main, "role-assignments")
