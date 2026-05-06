#!/usr/bin/env python3
"""
StratusScan-Azure — Azure RBAC export.

Pulls role assignments and custom role definitions per subscription via the
Authorization Management API. Resource Graph also exposes role assignments
(see resource_graph_export.py), but this script adds:
  • Custom role definitions (full role JSON: actions, dataActions, etc.)
  • Role-name resolution (joins built-in role names onto assignments)
  • Per-subscription view (one sheet pair per subscription)
"""

import logging
import sys
from pathlib import Path
from typing import Any, Dict, List

# Allow running as a script from /scripts/
_root = Path(__file__).parent.parent
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

from sslib.auth import get_credential, quiet_azure_loggers
from sslib.cloud import detect_cloud
from sslib.config import get_subscription_label, load_config
from sslib.output import make_filename, save_dataframes, snapshot_metadata
from sslib.subscriptions import filter_subscription_ids, list_subscriptions

logger = logging.getLogger(__name__)


def export_subscription(credential, subscription_id: str) -> Dict[str, List[Dict[str, Any]]]:
    """
    Return {assignments, role_definitions} for one subscription.
    """
    from azure.mgmt.authorization import AuthorizationManagementClient

    client = AuthorizationManagementClient(credential, subscription_id)
    scope = f"/subscriptions/{subscription_id}"

    role_defs_by_id: Dict[str, Dict[str, Any]] = {}
    role_defs_rows: List[Dict[str, Any]] = []
    for rd in client.role_definitions.list(scope=scope):
        perms = rd.permissions or []
        d = {
            "id": rd.id,
            "name": rd.name,
            "role_name": rd.role_name,
            "role_type": rd.role_type,
            "description": rd.description,
            "actions": "; ".join(a for p in perms for a in (p.actions or [])),
            "not_actions": "; ".join(a for p in perms for a in (p.not_actions or [])),
            "data_actions": "; ".join(a for p in perms for a in (p.data_actions or [])),
            "not_data_actions": "; ".join(
                a for p in perms for a in (p.not_data_actions or [])
            ),
            "assignable_scopes": "; ".join(rd.assignable_scopes or []),
        }
        role_defs_by_id[rd.id] = d
        role_defs_rows.append(d)

    assignment_rows: List[Dict[str, Any]] = []
    for ra in client.role_assignments.list_for_subscription():
        rdef = role_defs_by_id.get(ra.role_definition_id, {})
        assignment_rows.append(
            {
                "subscription_id": subscription_id,
                "role_name": rdef.get("role_name", ""),
                "role_type": rdef.get("role_type", ""),
                "principal_id": ra.principal_id,
                "principal_type": getattr(ra, "principal_type", ""),
                "scope": ra.scope,
                "role_definition_id": ra.role_definition_id,
                "id": ra.id,
            }
        )

    return {"assignments": assignment_rows, "role_definitions": role_defs_rows}


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    quiet_azure_loggers()

    try:
        import pandas as pd
    except ImportError:
        print("ERROR: pandas is required. Install with: pip install --user pandas openpyxl")
        return 1

    config = load_config()
    credential = get_credential()

    subs = list_subscriptions(credential)
    sub_ids = filter_subscription_ids(subs, config)
    if not sub_ids:
        print("No subscriptions in scope.")
        return 1

    sub_names = {s["id"]: s["name"] for s in subs}

    sheets: Dict[str, "pd.DataFrame"] = {}
    summary = []

    all_assignments: List[Dict[str, Any]] = []
    all_role_defs: List[Dict[str, Any]] = []

    for sub_id in sub_ids:
        label = get_subscription_label(config, sub_id, sub_names.get(sub_id, sub_id[:8]))
        print(f"  • {label} ({sub_id})...")
        try:
            data = export_subscription(credential, sub_id)
            all_assignments.extend(data["assignments"])
            # only keep custom role definitions (built-ins repeat across every sub)
            all_role_defs.extend(
                [r for r in data["role_definitions"] if r.get("role_type") == "CustomRole"]
            )
            summary.append(
                {
                    "Subscription": label,
                    "Subscription ID": sub_id,
                    "Assignments": len(data["assignments"]),
                    "Custom Roles": sum(
                        1 for r in data["role_definitions"] if r.get("role_type") == "CustomRole"
                    ),
                }
            )
        except Exception as e:
            logger.error("RBAC export failed for %s: %s", sub_id, e)
            summary.append(
                {
                    "Subscription": label,
                    "Subscription ID": sub_id,
                    "Assignments": f"ERROR: {e}",
                    "Custom Roles": 0,
                }
            )

    all_role_defs = list({r["id"]: r for r in all_role_defs}.values())

    sheets["Snapshot"] = snapshot_metadata(config, detect_cloud(), sub_count=len(sub_ids))
    sheets["Summary"] = pd.DataFrame(summary)
    sheets["Role Assignments"] = pd.DataFrame(all_assignments)
    sheets["Custom Role Definitions"] = pd.DataFrame(all_role_defs)

    tenant = config.get("tenant_name", "AZURE-TENANT")
    filename = make_filename(tenant, "rbac", "all")
    path = save_dataframes(sheets, filename)
    if path:
        print(f"\nWrote: {path}")
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
