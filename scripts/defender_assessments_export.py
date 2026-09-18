#!/usr/bin/env python3
"""StratusScanCLI-Azure — Defender Security Assessments Export

Assessments are listed at subscription scope; the list response carries no
metadata, so severity, category, description and remediation are joined from a
single assessments_metadata.list() call keyed by the assessment GUID.
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

utils.setup_logging("defender-assessments-export")
utils.log_script_start("defender_assessments_export.py", "Defender Security Assessments Export")

log = utils.get_logger()


def _resource_type_from_id(resource_id: str) -> str:
    parts = [p for p in resource_id.split("/") if p]
    lowered = [p.lower() for p in parts]
    if "providers" in lowered:
        p = len(lowered) - 1 - lowered[::-1].index("providers")
        if p + 1 >= len(parts):
            return ""
        return "/".join([parts[p + 1]] + parts[p + 2::2])
    if len(lowered) >= 4 and lowered[0] == "subscriptions" and lowered[2] == "resourcegroups":
        return "Microsoft.Resources/subscriptions/resourceGroups"
    if len(lowered) == 2 and lowered[0] == "subscriptions":
        return "Microsoft.Resources/subscriptions"
    return ""


def _extract_resource_info(resource_details) -> tuple:
    """Return (source, resource_id, resource_name, resource_type) for an assessment's resourceDetails."""
    if not resource_details:
        return "", "", "", ""
    source = utils.s(getattr(resource_details, "source", None))
    rid = utils.s(getattr(resource_details, "id", None))
    if rid:
        return source, rid, rid.rstrip("/").split("/")[-1], _resource_type_from_id(rid)
    machine_name = utils.s(getattr(resource_details, "machine_name", None))
    source_computer_id = utils.s(getattr(resource_details, "source_computer_id", None))
    return source, source_computer_id, machine_name, ""


def _iso(value: Any) -> str:
    return value.isoformat() if hasattr(value, "isoformat") else utils.s(value)


def collect_assessment_metadata(client, errors: list) -> dict[str, Any]:
    """Return {assessment GUID: SecurityAssessmentMetadataResponse}; empty (and recorded in errors) when the call fails."""
    log.info("Listing assessment metadata")
    try:
        return {utils.s(m.name): m for m in client.assessments_metadata.list() if getattr(m, "name", None)}
    except HttpResponseError as e:
        errors.append(utils.error_record("assessment metadata", "assessments_metadata.list", e))
        log.warning("Failed to list assessment metadata — severity/category/remediation will be blank: %s", e)
        return {}


def _build_row(a, metadata_map: dict[str, Any]) -> dict[str, Any]:
    name = utils.s(getattr(a, "name", None))
    metadata = metadata_map.get(name) or getattr(a, "metadata", None)
    status = getattr(a, "status", None)
    source, rid, rname, rtype = _extract_resource_info(getattr(a, "resource_details", None))

    categories = getattr(metadata, "categories", None) if metadata else None
    return {
        "Assessment Name": name,
        "Display Name": utils.s(getattr(a, "display_name", None)) or utils.s(getattr(metadata, "display_name", None)),
        "Status": utils.s(getattr(status, "code", None)),
        "Severity": utils.s(getattr(metadata, "severity", None)),
        "Category": ", ".join(utils.s(c) for c in categories) if categories else "",
        "Resource ID": rid,
        "Resource Name": rname,
        "Resource Type": rtype,
        "Description": utils.s(getattr(metadata, "description", None)),
        "Remediation": utils.s(getattr(metadata, "remediation_description", None)),
        "Resource Source": source,
        "Status Cause": utils.s(getattr(status, "cause", None)),
        "Status Description": utils.s(getattr(status, "description", None)),
        "First Evaluation Date": _iso(getattr(status, "first_evaluation_date", None)),
        "Status Change Date": _iso(getattr(status, "status_change_date", None)),
    }


def collect_assessments(subscription_id: str) -> tuple:
    """Return (rows, errors). The assessment listing itself is not caught: its failure is the run's failure."""
    client = utils.get_azure_client("security", subscription_id)
    log.info("Listing security assessments for subscription %s", subscription_id)

    rows = []
    errors: list = []
    metadata_map: dict[str, Any] = {}
    metadata_loaded = False
    for a in client.assessments.list(scope=f"/subscriptions/{subscription_id}"):
        if not metadata_loaded:
            metadata_map = collect_assessment_metadata(client, errors)
            metadata_loaded = True
        rows.append(_build_row(a, metadata_map))

    return rows, errors


def main(subscription_id: str, subscription_name: str) -> utils.ExportResult:
    environment = utils.detect_environment()
    if not utils.is_service_available_in_environment("security", environment):
        sys.exit(0)

    rows, errors = collect_assessments(subscription_id)

    if not rows:
        raise utils.NoResourcesFound("security assessments")

    df = pd.DataFrame(rows)
    filename = utils.create_export_filename(subscription_name, "defender-assessments", "all")
    utils.save_dataframe_to_excel(df, filename, errors=errors)
    print(f"Exported {len(rows)} assessment(s) → {filename}")
    log.info("Export complete: %d assessments", len(rows))
    return utils.ExportResult(rows=len(rows), filename=filename, errors=errors)


if __name__ == "__main__":
    import runner

    runner.run_exporter(main, "defender-assessments")
