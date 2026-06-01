#!/usr/bin/env python3
"""StratusScanCLI-Azure — RBAC Role Assignments Export"""

import sys
from pathlib import Path

try:
    import utils
except ImportError:
    sys.path.append(str(Path(__file__).parent.parent))
    import utils

import pandas as pd

utils.setup_logging("role-assignments-export")
utils.log_script_start("role_assignments_export.py", "Azure RBAC Role Assignments Export")

log = utils.get_logger()


def collect_role_assignments(subscription_id: str) -> list:
    client = utils.get_azure_client("authorization", subscription_id)
    scope = f"/subscriptions/{subscription_id}"
    log.info("Listing role assignments for subscription %s", subscription_id)
    return list(client.role_assignments.list_for_scope(scope))


def _role_name_from_id(role_definition_id: str) -> str:
    """Extract the role definition GUID from the full resource ID."""
    try:
        return role_definition_id.split("/")[-1]
    except Exception:
        return role_definition_id or ""


def _scope_type(scope: str) -> str:
    """Classify an assignment scope as subscription/resource-group/resource."""
    if not scope:
        return ""
    parts = scope.strip("/").split("/")
    if len(parts) == 2 and parts[0].lower() == "subscriptions":
        return "Subscription"
    if len(parts) == 4 and parts[2].lower() == "resourcegroups":
        return "Resource Group"
    return "Resource"


def main(subscription_id: str, subscription_name: str) -> None:
    environment = utils.detect_environment()
    if not utils.is_service_available_in_environment("authorization", environment):
        sys.exit(0)

    assignments = collect_role_assignments(subscription_id)
    if not assignments:
        print("No role assignments found.")
        return

    rows = []
    for ra in assignments:
        rows.append({
            "Assignment ID": ra.name,
            "Principal ID": ra.principal_id or "",
            "Principal Type": str(ra.principal_type) if ra.principal_type else "",
            "Role Definition ID": _role_name_from_id(ra.role_definition_id or ""),
            "Scope": ra.scope or "",
            "Scope Type": _scope_type(ra.scope or ""),
            "Created On": (
                ra.created_on.strftime("%Y-%m-%d %H:%M:%S")
                if ra.created_on else ""
            ),
        })

    df = pd.DataFrame(rows)
    filename = utils.create_export_filename(subscription_name, "role-assignments", "all")
    utils.save_dataframe_to_excel(df, filename, sheet_name="Role Assignments")
    print(f"Exported {len(rows)} role assignment(s) → {filename}")
    log.info("Export complete: %d role assignments", len(rows))


if __name__ == "__main__":
    cfg = utils.get_config()
    sub_id = cfg.get("default_subscription_id", "")
    sub_name = utils.get_subscription_name(sub_id)
    if not sub_id:
        print("ERROR: No subscription configured. Run configure.py first.")
        sys.exit(1)
    main(sub_id, sub_name)
