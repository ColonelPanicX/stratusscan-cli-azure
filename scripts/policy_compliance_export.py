#!/usr/bin/env python3
"""StratusScanCLI-Azure — Policy Compliance State Export"""

import sys
from collections import Counter
from pathlib import Path

try:
    import utils
except ImportError:
    sys.path.append(str(Path(__file__).parent.parent))
    import utils

import pandas as pd

utils.setup_logging("policy-compliance-export")
utils.log_script_start("policy_compliance_export.py", "Policy Compliance State Export")

log = utils.get_logger()


def collect_states(subscription_id: str) -> list:
    client = utils.get_azure_client("policyinsights", subscription_id)
    log.info("Querying latest policy compliance states for subscription %s", subscription_id)
    return list(
        client.policy_states.list_query_results_for_subscription("latest", subscription_id)
    )


def _detail_rows(states: list) -> list:
    rows = []
    for st in states:
        resource_id = getattr(st, "resource_id", "") or ""
        rows.append({
            "Resource": resource_id.split("/")[-1],
            "Resource Type": getattr(st, "resource_type", "") or "",
            "Resource Group": utils.extract_resource_group(resource_id),
            "Location": getattr(st, "resource_location", "") or "",
            "Compliance State": getattr(st, "compliance_state", "") or "",
            "Policy Assignment": getattr(st, "policy_assignment_name", "") or "",
            "Policy Definition": getattr(st, "policy_definition_name", "") or "",
            "Definition Action": getattr(st, "policy_definition_action", "") or "",
            "Definition Category": getattr(st, "policy_definition_category", "") or "",
            "Timestamp": str(getattr(st, "timestamp", "")) if getattr(st, "timestamp", None) else "",
        })
    return rows


def _summary_rows(detail_rows: list) -> list:
    counts = Counter(r["Compliance State"] or "unknown" for r in detail_rows)
    total = sum(counts.values())
    rows = [{"Compliance State": state, "Count": n,
             "Percent": f"{(n / total * 100):.1f}%" if total else "0%"}
            for state, n in counts.most_common()]
    rows.append({"Compliance State": "TOTAL", "Count": total, "Percent": "100%"})
    return rows


def main(subscription_id: str, subscription_name: str) -> None:
    environment = utils.detect_environment()
    if not utils.is_service_available_in_environment("policyinsights", environment):
        sys.exit(0)

    states = collect_states(subscription_id)
    if not states:
        print("No policy compliance states found.")
        return

    details = _detail_rows(states)
    sheets = {
        "Compliance Summary": pd.DataFrame(_summary_rows(details)),
        "Compliance Detail": pd.DataFrame(details),
    }

    filename = utils.create_export_filename(subscription_name, "policy-compliance", "all")
    utils.save_multiple_dataframes_to_excel(sheets, filename)
    print(f"Exported {len(details)} policy compliance record(s) → {filename}")
    log.info("Export complete: %d compliance records", len(details))


if __name__ == "__main__":
    sub_id, sub_name = utils.resolve_target_subscription()
    if not sub_id:
        print("ERROR: No subscription configured. Run configure.py first.")
        sys.exit(1)
    main(sub_id, sub_name)
