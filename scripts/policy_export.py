#!/usr/bin/env python3
"""
StratusScan-Azure — Azure Policy export.

Pulls policy assignments, definitions (custom only), and current compliance
state per subscription. Compliance state comes from Policy Insights and
reflects the most recent evaluation.
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
from sslib.cloud import arm_client_kwargs, detect_cloud
from sslib.config import get_subscription_label, load_config, resolve_scope_label
from sslib.output import make_filename, save_dataframes, snapshot_metadata
from sslib.subscriptions import filter_subscription_ids, list_subscriptions

logger = logging.getLogger(__name__)


def list_assignments(credential, subscription_id: str) -> List[Dict[str, Any]]:
    from azure.mgmt.resource.policy import PolicyClient

    client = PolicyClient(credential, subscription_id, **arm_client_kwargs())
    rows = []
    for a in client.policy_assignments.list():
        rows.append(
            {
                "subscription_id": subscription_id,
                "name": a.name,
                "display_name": a.display_name,
                "policy_definition_id": a.policy_definition_id,
                "scope": getattr(a, "scope", ""),
                "enforcement_mode": getattr(a, "enforcement_mode", ""),
                "description": a.description,
                "id": a.id,
            }
        )
    return rows


def list_custom_definitions(credential, subscription_id: str) -> List[Dict[str, Any]]:
    from azure.mgmt.resource.policy import PolicyClient

    client = PolicyClient(credential, subscription_id, **arm_client_kwargs())
    rows = []
    for d in client.policy_definitions.list():
        if d.policy_type == "Custom":
            rows.append(
                {
                    "subscription_id": subscription_id,
                    "name": d.name,
                    "display_name": d.display_name,
                    "mode": d.mode,
                    "description": d.description,
                    "id": d.id,
                }
            )
    return rows


def list_compliance_summary(credential, subscription_id: str) -> List[Dict[str, Any]]:
    """
    Aggregate non-compliant resource counts per assignment via Policy Insights.

    Raises on failure so the caller's per-subscription error handling surfaces
    the problem in the Summary sheet — silently swallowing here produced
    misleading "Non-Compliant Assignments: 0" rows for subs where the API
    actually errored (e.g. missing read permission).
    """
    from azure.mgmt.policyinsights import PolicyInsightsClient

    client = PolicyInsightsClient(credential, subscription_id, **arm_client_kwargs())
    rows: List[Dict[str, Any]] = []
    result = client.policy_states.summarize_for_subscription(subscription_id=subscription_id)
    for sub_summary in (result.value or []):
        for assignment in (getattr(sub_summary, "policy_assignments", None) or []):
            results = getattr(assignment, "results", None)
            rows.append(
                {
                    "subscription_id": subscription_id,
                    "policy_assignment_id": assignment.policy_assignment_id,
                    "non_compliant_resources": getattr(results, "non_compliant_resources", 0),
                    "non_compliant_policies": getattr(results, "non_compliant_policies", 0),
                }
            )
    return rows


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

    all_assignments: List[Dict[str, Any]] = []
    all_definitions: List[Dict[str, Any]] = []
    all_compliance: List[Dict[str, Any]] = []
    summary = []

    for sub_id in sub_ids:
        label = get_subscription_label(config, sub_id, sub_names.get(sub_id, sub_id[:8]))
        print(f"  • {label} ({sub_id})...")

        try:
            a = list_assignments(credential, sub_id)
            all_assignments.extend(a)
            a_status: Any = len(a)
        except Exception as e:
            logger.error("Assignments failed for %s: %s", sub_id, e)
            a_status = f"ERROR: {e}"

        try:
            d = list_custom_definitions(credential, sub_id)
            all_definitions.extend(d)
            d_status: Any = len(d)
        except Exception as e:
            logger.error("Custom definitions failed for %s: %s", sub_id, e)
            d_status = f"ERROR: {e}"

        try:
            c = list_compliance_summary(credential, sub_id)
            all_compliance.extend(c)
            non_compliant: Any = sum(
                1 for r in c if int(r.get("non_compliant_resources") or 0) > 0
            )
        except Exception as e:
            logger.error("Compliance summary failed for %s: %s", sub_id, e)
            non_compliant = f"ERROR: {e}"

        summary.append(
            {
                "Subscription": label,
                "Assignments": a_status,
                "Custom Definitions": d_status,
                "Non-Compliant Assignments": non_compliant,
            }
        )

    sheets = {
        "Snapshot": snapshot_metadata(config, detect_cloud(), sub_count=len(sub_ids)),
        "Summary": pd.DataFrame(summary),
        "Assignments": pd.DataFrame(all_assignments),
        "Custom Definitions": pd.DataFrame(all_definitions),
        "Compliance": pd.DataFrame(all_compliance),
    }

    filename = make_filename(resolve_scope_label(config, sub_ids), "policy", "all")
    path = save_dataframes(sheets, filename)
    if path:
        print(f"\nWrote: {path}")
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
