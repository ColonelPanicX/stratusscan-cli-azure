#!/usr/bin/env python3
"""StratusScanCLI-Azure — Defender Security Assessments Export"""

import sys
from pathlib import Path

try:
    import utils
except ImportError:
    sys.path.append(str(Path(__file__).parent.parent.parent))
    import utils

import pandas as pd

utils.setup_logging("defender-assessments-export")
utils.log_script_start("defender_assessments_export.py", "Defender Security Assessments Export")

log = utils.get_logger()


def _extract_resource_info(resource_details) -> tuple:
    if not resource_details:
        return "", "", ""
    source = getattr(resource_details, "source", None) or resource_details
    rid = getattr(source, "id", "") or ""
    parts = rid.split("/") if rid else []
    rname = parts[-1] if len(parts) > 1 else ""
    rtype = ""
    if len(parts) >= 2:
        rtype = "/".join(parts[-2:]) if not parts[-2].startswith("Microsoft.") else "/".join(parts[-3:-1])
    return rid, rname, rtype


def _status_code(status) -> str:
    if not status:
        return ""
    code = getattr(status, "code", "") or ""
    return str(code)


def collect_assessments(subscription_id: str) -> list:
    client = utils.get_azure_client("security", subscription_id)
    log.info("Listing security assessments for subscription %s", subscription_id)

    rows = []
    try:
        for a in client.assessments.list(scope=f"/subscriptions/{subscription_id}"):
            status = getattr(a, "status", None)
            status_code = _status_code(status)

            metadata = getattr(a, "metadata", None) if hasattr(a, "metadata") else None
            display_name = ""
            severity = ""
            category = ""
            description = ""
            remediation = ""

            if metadata:
                display_name = getattr(metadata, "display_name", "") or ""
                severity = getattr(metadata, "severity", "") or ""
                categories = getattr(metadata, "categories", None)
                if categories:
                    category = ", ".join(str(c) for c in categories)
                description = getattr(metadata, "description", "") or ""
                remediation = getattr(metadata, "remediation_description", "") or ""

            resource_details = getattr(a, "resource_details", None)
            rid, rname, rtype = _extract_resource_info(resource_details)

            rows.append({
                "Assessment Name": getattr(a, "name", "") or "",
                "Display Name": display_name or getattr(a, "display_name", "") or "",
                "Status": status_code,
                "Severity": severity,
                "Category": category,
                "Resource ID": rid,
                "Resource Name": rname,
                "Resource Type": rtype,
                "Description": description,
                "Remediation": remediation,
            })
    except Exception as e:
        log.warning("Failed to list assessments: %s", e)

    return rows


def main(subscription_id: str, subscription_name: str) -> None:
    environment = utils.detect_environment()
    if not utils.is_service_available_in_environment("resource", environment):
        sys.exit(0)

    rows = collect_assessments(subscription_id)

    if not rows:
        print("No security assessments found.")
        return

    df = pd.DataFrame(rows)
    filename = utils.create_export_filename(subscription_name, "defender-assessments", "all")
    utils.save_dataframe_to_excel(df, filename)
    print(f"Exported {len(rows)} assessment(s) → {filename}")
    log.info("Export complete: %d assessments", len(rows))


if __name__ == "__main__":
    sub_id, sub_name = utils.resolve_target_subscription()
    if not sub_id:
        print("ERROR: No subscription configured. Run configure.py first.")
        sys.exit(1)
    main(sub_id, sub_name)
