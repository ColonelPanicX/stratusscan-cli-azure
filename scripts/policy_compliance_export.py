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


def _build_detail_row(st) -> dict:
    resource_id = utils.s(getattr(st, "resource_id", None))
    group_names = getattr(st, "policy_definition_group_names", None) or []
    return {
        "Resource": resource_id.split("/")[-1],
        "Resource Type": utils.s(getattr(st, "resource_type", None)),
        "Resource Group": utils.extract_resource_group(resource_id),
        "Location": utils.s(getattr(st, "resource_location", None)),
        "Compliance State": utils.s(getattr(st, "compliance_state", None)),
        "Policy Assignment": utils.s(getattr(st, "policy_assignment_name", None)),
        "Policy Definition": utils.s(getattr(st, "policy_definition_name", None)),
        "Definition Action": utils.s(getattr(st, "policy_definition_action", None)),
        "Definition Category": utils.s(getattr(st, "policy_definition_category", None)),
        "Timestamp": utils.s(getattr(st, "timestamp", None)),
        "Policy Set Definition": utils.s(getattr(st, "policy_set_definition_name", None)),
        "Definition Reference ID": utils.s(getattr(st, "policy_definition_reference_id", None)),
        "Definition Group Names": ", ".join(utils.s(g) for g in group_names),
        "Assignment Scope": utils.s(getattr(st, "policy_assignment_scope", None)),
    }


def _detail_rows(states: list) -> list:
    return [_build_detail_row(st) for st in states]


def _summary_rows(detail_rows: list) -> list:
    counts = Counter(r["Compliance State"] or "unknown" for r in detail_rows)
    total = sum(counts.values())
    rows = [{"Compliance State": state, "Count": n,
             "Percent": f"{(n / total * 100):.1f}%" if total else "0%"}
            for state, n in counts.most_common()]
    rows.append({"Compliance State": "TOTAL", "Count": total, "Percent": "100%"})
    return rows


def main(subscription_id: str, subscription_name: str) -> utils.ExportResult:
    environment = utils.detect_environment()
    if not utils.is_service_available_in_environment("policyinsights", environment):
        sys.exit(0)

    states = collect_states(subscription_id)
    if not states:
        raise utils.NoResourcesFound("policy compliance states")

    details = _detail_rows(states)
    sheets = {
        "Compliance Summary": pd.DataFrame(_summary_rows(details)),
        "Compliance Detail": pd.DataFrame(details),
    }

    filename = utils.create_export_filename(subscription_name, "policy-compliance", "all")
    utils.save_multiple_dataframes_to_excel(sheets, filename)
    print(f"Exported {len(details)} policy compliance record(s) → {filename}")
    log.info("Export complete: %d compliance records", len(details))
    return utils.ExportResult(rows=len(details), filename=filename, errors=[])


if __name__ == "__main__":
    import runner

    runner.run_exporter(main, "policy-compliance")
