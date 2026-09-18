#!/usr/bin/env python3
"""StratusScanCLI-Azure — Azure Advisor Recommendations Export"""

import json
import re
import sys
from pathlib import Path

try:
    import utils
except ImportError:
    sys.path.append(str(Path(__file__).parent.parent))
    import utils

import pandas as pd

utils.setup_logging("advisor-export")
utils.log_script_start("advisor_export.py", "Azure Advisor Recommendations Export")

log = utils.get_logger()

_RECOMMENDATION_SUFFIX = re.compile(
    r"/providers/Microsoft\.Advisor/recommendations/[^/]+/?$", re.IGNORECASE
)


def _parse_resource_id(resource_id: str) -> tuple:
    """Return (name, type) for an ARM resource ID, e.g. ("d1", "Microsoft.Sql/servers/databases").

    The last `providers` segment wins, so extension and nested child resources resolve to
    their own type. Subscription and resource group scopes carry no `providers` segment.
    """
    parts = [p for p in (resource_id or "").split("/") if p]
    lowered = [p.lower() for p in parts]

    if "providers" in lowered:
        start = len(lowered) - lowered[::-1].index("providers")
        namespace, segments = parts[start : start + 1], parts[start + 1 :]
        if not namespace or not segments:
            return "", ""
        rtype = "/".join(namespace + segments[0::2])
        rname = segments[-1] if len(segments) % 2 == 0 else ""
        return rname, rtype

    if len(parts) == 2 and lowered[0] == "subscriptions":
        return parts[1], "Microsoft.Resources/subscriptions"
    if len(parts) == 4 and lowered[0] == "subscriptions" and lowered[2] == "resourcegroups":
        return parts[3], "Microsoft.Resources/subscriptions/resourceGroups"
    return "", ""


def _resolve_resource_id(rec) -> str:
    """Assessed resource ID, else the scope the recommendation ID hangs off, else blank.

    `impacted_field` is a resource type, never an ID — it must not be used here.
    """
    metadata = getattr(rec, "resource_metadata", None)
    resource_id = getattr(metadata, "resource_id", None) or ""
    if resource_id:
        return resource_id

    rec_id = getattr(rec, "id", None) or ""
    scope, matched = _RECOMMENDATION_SUFFIX.subn("", rec_id)
    return scope if matched else ""


def _to_number(value):
    """Coerce an extendedProperties value to a number. ARM returns these as strings."""
    if value is None or value == "":
        return ""
    try:
        return float(value)
    except (TypeError, ValueError):
        return ""


_REGION_KEYS = ("region", "Region", "location")


def _extract_savings(extended_properties: dict) -> dict:
    """Split Advisor savings into explicit monthly and annual fields.

    Advisor cost recommendations expose both periods in extendedProperties. Emitting
    one collapsed figure loses which period it came from — a 12x ambiguity. Keys that
    are absent stay blank rather than being derived from the other period.
    """
    blank = {
        "Potential Savings (Monthly)": "",
        "Potential Savings (Annual)": "",
        "Savings Currency": "",
        "Reservation Term": "",
        "Lookback (days)": "",
        "Region": "",
    }
    if not extended_properties:
        return blank

    monthly = _to_number(extended_properties.get("savingsAmount"))
    annual = _to_number(extended_properties.get("annualSavingsAmount"))

    currency = ""
    if monthly != "" or annual != "":
        currency = extended_properties.get("savingsCurrency") or ""

    lookback = extended_properties.get("lookbackPeriod") or ""
    lookback_number = _to_number(lookback)

    return {
        "Potential Savings (Monthly)": monthly,
        "Potential Savings (Annual)": annual,
        "Savings Currency": currency,
        "Reservation Term": extended_properties.get("term") or "",
        "Lookback (days)": lookback_number if lookback_number != "" else lookback,
        "Region": next(
            (extended_properties[k] for k in _REGION_KEYS if extended_properties.get(k)), ""
        ),
    }


def _build_row(rec) -> dict:
    resource_id = _resolve_resource_id(rec)
    parsed_name, parsed_type = _parse_resource_id(resource_id)

    extended = getattr(rec, "extended_properties", None) or {}
    short_desc = getattr(rec, "short_description", None)

    last_updated = getattr(rec, "last_updated", "") or ""
    if hasattr(last_updated, "isoformat"):
        last_updated = last_updated.isoformat()

    row = {
        "Category": utils.s(getattr(rec, "category", None)),
        "Impact": utils.s(getattr(rec, "impact", None)),
        "Resource ID": resource_id,
        "Resource Name": getattr(rec, "impacted_value", None) or parsed_name,
        "Resource Type": getattr(rec, "impacted_field", None) or parsed_type,
        "Recommendation": getattr(short_desc, "problem", None) or "",
        "Solution": getattr(short_desc, "solution", None) or "",
    }
    row.update(_extract_savings(extended))
    row["Last Updated"] = last_updated
    row["Recommendation Type ID"] = utils.s(getattr(rec, "recommendation_type_id", None))
    row["Extended Properties (JSON)"] = (
        json.dumps(extended, sort_keys=True, default=str) if extended else ""
    )
    return row


def collect_recommendations(subscription_id: str) -> list:
    client = utils.get_azure_client("advisor", subscription_id)
    log.info("Listing Advisor recommendations for subscription %s", subscription_id)

    return [_build_row(rec) for rec in client.recommendations.list()]


def main(subscription_id: str, subscription_name: str) -> utils.ExportResult:
    environment = utils.detect_environment()
    if not utils.is_service_available_in_environment("resource", environment):
        sys.exit(0)

    rows = collect_recommendations(subscription_id)

    if not rows:
        raise utils.NoResourcesFound("Advisor recommendations")

    df = pd.DataFrame(rows)
    filename = utils.create_export_filename(subscription_name, "advisor-recommendations", "all")
    utils.save_dataframe_to_excel(df, filename)
    print(f"Exported {len(rows)} recommendation(s) → {filename}")
    log.info("Export complete: %d recommendations", len(rows))
    return utils.ExportResult(rows=len(rows), filename=filename, errors=[])


if __name__ == "__main__":
    import runner

    runner.run_exporter(main, "advisor")
