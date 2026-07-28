#!/usr/bin/env python3
"""StratusScanCLI-Azure — Azure Advisor Recommendations Export"""

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


def _parse_resource_id(resource_id: str) -> tuple:
    if not resource_id:
        return "", ""
    parts = resource_id.split("/")
    rname = parts[-1] if len(parts) > 1 else ""
    rtype = ""
    for i, p in enumerate(parts):
        if p.lower() == "providers" and i + 2 < len(parts):
            rtype = "/".join(parts[i + 1 : i + 3])
            break
    return rname, rtype


_MONTHLY_SAVINGS_KEYS = ("savingsAmount", "monthlySavingsAmount")
_ANNUAL_SAVINGS_KEYS = ("annualSavingsAmount", "estimatedAnnualSavings")


def _to_number(value):
    """Coerce an extendedProperties value to a number. ARM returns these as strings."""
    if value is None or value == "":
        return ""
    try:
        return float(value)
    except (TypeError, ValueError):
        return ""


def _first_number(extended_properties: dict, keys):
    for key in keys:
        number = _to_number(extended_properties.get(key))
        if number != "":
            return number
    return ""


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

    monthly = _first_number(extended_properties, _MONTHLY_SAVINGS_KEYS)
    annual = _first_number(extended_properties, _ANNUAL_SAVINGS_KEYS)

    currency = ""
    if monthly != "" or annual != "":
        currency = extended_properties.get("savingsCurrency") or "USD"

    lookback = extended_properties.get("lookbackPeriod") or ""
    lookback_number = _to_number(lookback)

    return {
        "Potential Savings (Monthly)": monthly,
        "Potential Savings (Annual)": annual,
        "Savings Currency": currency,
        "Reservation Term": extended_properties.get("term") or "",
        "Lookback (days)": lookback_number if lookback_number != "" else lookback,
        "Region": extended_properties.get("region") or "",
    }


def collect_recommendations(subscription_id: str) -> list:
    client = utils.get_azure_client("advisor", subscription_id)
    log.info("Listing Advisor recommendations for subscription %s", subscription_id)

    rows = []
    try:
        for rec in client.recommendations.list():
            resource_id = getattr(rec, "resource_id", "") or getattr(rec, "impacted_field", "") or ""
            rname, rtype = _parse_resource_id(resource_id)

            extended = getattr(rec, "extended_properties", None) or {}
            short_desc = getattr(rec, "short_description", None)
            problem = ""
            solution = ""
            if short_desc:
                problem = getattr(short_desc, "problem", "") or ""
                solution = getattr(short_desc, "solution", "") or ""

            last_updated = getattr(rec, "last_updated", "") or ""
            if hasattr(last_updated, "isoformat"):
                last_updated = last_updated.isoformat()

            row = {
                "Category": getattr(rec, "category", "") or "",
                "Impact": getattr(rec, "impact", "") or "",
                "Resource ID": resource_id,
                "Resource Name": rname or getattr(rec, "impacted_value", "") or "",
                "Resource Type": rtype or getattr(rec, "impacted_field", "") or "",
                "Recommendation": problem,
                "Solution": solution,
            }
            row.update(_extract_savings(extended))
            row["Last Updated"] = last_updated
            rows.append(row)
    except Exception as e:
        log.warning("Failed to list Advisor recommendations: %s", e)

    return rows


def main(subscription_id: str, subscription_name: str) -> None:
    environment = utils.detect_environment()
    if not utils.is_service_available_in_environment("resource", environment):
        sys.exit(0)

    rows = collect_recommendations(subscription_id)

    if not rows:
        print("No Advisor recommendations found.")
        return

    df = pd.DataFrame(rows)
    filename = utils.create_export_filename(subscription_name, "advisor-recommendations", "all")
    utils.save_dataframe_to_excel(df, filename)
    print(f"Exported {len(rows)} recommendation(s) → {filename}")
    log.info("Export complete: %d recommendations", len(rows))


if __name__ == "__main__":
    sub_id, sub_name = utils.resolve_target_subscription()
    if not sub_id:
        print("ERROR: No subscription configured. Run configure.py first.")
        sys.exit(1)
    main(sub_id, sub_name)
