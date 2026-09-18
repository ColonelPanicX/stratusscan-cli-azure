#!/usr/bin/env python3
"""StratusScanCLI-Azure — Defender for Cloud Regulatory Compliance Export

One sheet of compliance standards attached to the subscription and one sheet of
their controls — the FedRAMP / NIST evidence an assessor asks for in a single
workbook.

Controls are listed per standard; a standard whose controls cannot be listed is
recorded on the Errors sheet (PARTIAL) and the rest of the export continues.
What comes back is scoped by Defender for Cloud itself: the Microsoft cloud
security benchmark is assigned by default, other standards can only be added
once at least one paid Defender plan is enabled, a standard with no relevant
resources in the subscription is not reported even when it is assigned, and the
set of standards offered differs between Azure and Azure Government.
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

log = utils.get_logger()

STANDARD_COLUMNS = [
    "Standard", "State", "Passed Controls", "Failed Controls",
    "Skipped Controls", "Unsupported Controls",
]
CONTROL_COLUMNS = [
    "Standard", "Control", "State", "Passed Assessments",
    "Failed Assessments", "Skipped Assessments", "Description",
]


def collect_standards(client) -> list:
    log.info("Listing regulatory compliance standards")
    return list(client.regulatory_compliance_standards.list())


def _standard_row(standard) -> dict[str, Any]:
    return {
        "Standard": utils.s(getattr(standard, "name", None)),
        "State": utils.s(getattr(standard, "state", None)),
        "Passed Controls": utils.s(getattr(standard, "passed_controls", None)),
        "Failed Controls": utils.s(getattr(standard, "failed_controls", None)),
        "Skipped Controls": utils.s(getattr(standard, "skipped_controls", None)),
        "Unsupported Controls": utils.s(getattr(standard, "unsupported_controls", None)),
    }


def _control_row(control, standard_name: str) -> dict[str, Any]:
    return {
        "Standard": standard_name,
        "Control": utils.s(getattr(control, "name", None)),
        "State": utils.s(getattr(control, "state", None)),
        "Passed Assessments": utils.s(getattr(control, "passed_assessments", None)),
        "Failed Assessments": utils.s(getattr(control, "failed_assessments", None)),
        "Skipped Assessments": utils.s(getattr(control, "skipped_assessments", None)),
        "Description": utils.s(getattr(control, "description", None)),
    }


def collect_controls(client, standards: list, errors: list) -> list[dict[str, Any]]:
    rows = []
    for standard in standards:
        standard_name = utils.s(getattr(standard, "name", None))
        try:
            controls = list(client.regulatory_compliance_controls.list(standard_name))
        except HttpResponseError as e:
            errors.append(utils.error_record(standard_name, "regulatory_compliance_controls.list", e))
            log.warning("Failed to list controls for standard %s: %s", standard_name, e)
            continue
        rows.extend(_control_row(control, standard_name) for control in controls)
    return rows


def main(subscription_id: str, subscription_name: str) -> utils.ExportResult:
    environment = utils.detect_environment()
    if not utils.is_service_available_in_environment("security", environment):
        sys.exit(0)

    client = utils.get_azure_client("security", subscription_id)
    standards = collect_standards(client)
    if not standards:
        raise utils.NoResourcesFound("regulatory compliance standards")

    errors: list = []
    standard_rows = [_standard_row(standard) for standard in standards]
    control_rows = collect_controls(client, standards, errors)

    sheets = {
        "Standards": pd.DataFrame(standard_rows, columns=STANDARD_COLUMNS),
        "Controls": pd.DataFrame(control_rows, columns=CONTROL_COLUMNS),
    }
    filename = utils.create_export_filename(subscription_name, "regulatory-compliance", "all")
    utils.save_multiple_dataframes_to_excel(sheets, filename, errors=errors)
    print(f"Exported {len(standard_rows)} standard(s) and {len(control_rows)} control(s) → {filename}")
    log.info(
        "Export complete: %d standards, %d controls", len(standard_rows), len(control_rows)
    )
    return utils.ExportResult(rows=len(standard_rows), filename=filename, errors=errors)


if __name__ == "__main__":
    import runner

    runner.run_exporter(main, "regulatory-compliance")
