#!/usr/bin/env python3
"""StratusScanCLI-Azure — Policy Compliance State Export

Detail sheet: the latest NonCompliant policy states, server-side filtered with
$filter=complianceState eq 'NonCompliant' so the export never materializes every
resource × policy pair. Summary sheet: the service's own summarize action
(non-compliant resource and policy counts per subscription, assignment and
definition) instead of counting client-side.
"""

import sys
from pathlib import Path

try:
    import utils
except ImportError:
    sys.path.append(str(Path(__file__).parent.parent))
    import utils

import pandas as pd
from azure.mgmt.policyinsights.models import QueryOptions

log = utils.get_logger()

NON_COMPLIANT_FILTER = "complianceState eq 'NonCompliant'"

SUMMARY_COLUMNS = [
    "Level", "Policy Assignment", "Policy Set Definition", "Policy Definition",
    "Definition Reference ID", "Effect", "Non-Compliant Resources", "Non-Compliant Policies",
]


def collect_states(subscription_id: str) -> list:
    client = utils.get_azure_client("policyinsights", subscription_id)
    log.info("Querying latest non-compliant policy states for subscription %s", subscription_id)
    return list(
        client.policy_states.list_query_results_for_subscription(
            "latest", subscription_id, query_options=QueryOptions(filter=NON_COMPLIANT_FILTER)
        )
    )


def collect_summary(subscription_id: str):
    client = utils.get_azure_client("policyinsights", subscription_id)
    log.info("Summarizing latest policy states for subscription %s", subscription_id)
    return client.policy_states.summarize_for_subscription("latest", subscription_id)


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


def _last_segment(resource_id) -> str:
    return utils.s(resource_id).rstrip("/").split("/")[-1]


def _counts(results) -> tuple:
    non_compliant_resources = getattr(results, "non_compliant_resources", None)
    non_compliant_policies = getattr(results, "non_compliant_policies", None)
    return (
        non_compliant_resources if non_compliant_resources is not None else "",
        non_compliant_policies if non_compliant_policies is not None else "",
    )


def _summary_rows(summary) -> list:
    """Flatten SummarizeResults: one subscription row, one per assignment, one per definition."""
    rows = []
    for entry in getattr(summary, "value", None) or []:
        resources, policies = _counts(getattr(entry, "results", None))
        rows.append({
            "Level": "Subscription", "Policy Assignment": "", "Policy Set Definition": "",
            "Policy Definition": "", "Definition Reference ID": "", "Effect": "",
            "Non-Compliant Resources": resources, "Non-Compliant Policies": policies,
        })
        for assignment in getattr(entry, "policy_assignments", None) or []:
            assignment_name = _last_segment(getattr(assignment, "policy_assignment_id", None))
            set_name = _last_segment(getattr(assignment, "policy_set_definition_id", None))
            resources, policies = _counts(getattr(assignment, "results", None))
            rows.append({
                "Level": "Assignment", "Policy Assignment": assignment_name,
                "Policy Set Definition": set_name, "Policy Definition": "",
                "Definition Reference ID": "", "Effect": "",
                "Non-Compliant Resources": resources, "Non-Compliant Policies": policies,
            })
            for definition in getattr(assignment, "policy_definitions", None) or []:
                resources, _ = _counts(getattr(definition, "results", None))
                rows.append({
                    "Level": "Definition", "Policy Assignment": assignment_name,
                    "Policy Set Definition": set_name,
                    "Policy Definition": _last_segment(getattr(definition, "policy_definition_id", None)),
                    "Definition Reference ID": utils.s(getattr(definition, "policy_definition_reference_id", None)),
                    "Effect": utils.s(getattr(definition, "effect", None)),
                    "Non-Compliant Resources": resources, "Non-Compliant Policies": "",
                })
    return rows


def main(subscription_id: str, subscription_name: str) -> utils.ExportResult:
    environment = utils.detect_environment()
    if not utils.is_service_available_in_environment("policyinsights", environment):
        sys.exit(0)

    summary_rows = _summary_rows(collect_summary(subscription_id))
    states = collect_states(subscription_id)
    if not states and not summary_rows:
        raise utils.NoResourcesFound("policy compliance states")

    details = _detail_rows(states)
    sheets = {
        "Compliance Summary": pd.DataFrame(summary_rows, columns=SUMMARY_COLUMNS),
        "Compliance Detail": pd.DataFrame(details),
    }

    filename = utils.create_export_filename(subscription_name, "policy-compliance", "all")
    utils.save_multiple_dataframes_to_excel(sheets, filename)
    print(f"Exported {len(details)} non-compliant policy state(s), {len(summary_rows)} summary row(s) → {filename}")
    log.info("Export complete: %d non-compliant states, %d summary rows", len(details), len(summary_rows))
    return utils.ExportResult(rows=len(details), filename=filename, errors=[])


if __name__ == "__main__":
    import runner

    runner.run_exporter(main, "policy-compliance")
