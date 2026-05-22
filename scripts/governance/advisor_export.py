#!/usr/bin/env python3
"""StratusScanCLI-Azure — Azure Advisor Recommendations Export"""

import sys
from pathlib import Path

try:
    import utils
except ImportError:
    sys.path.append(str(Path(__file__).parent.parent.parent))
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


def _extract_savings(extended_properties: dict) -> str:
    if not extended_properties:
        return ""
    for key in ("savingsAmount", "annualSavingsAmount", "estimatedAnnualSavings", "savings"):
        val = extended_properties.get(key)
        if val is not None:
            currency = extended_properties.get("savingsCurrency", "USD")
            return f"{val} {currency}"
    return ""


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

            rows.append({
                "Category": getattr(rec, "category", "") or "",
                "Impact": getattr(rec, "impact", "") or "",
                "Resource ID": resource_id,
                "Resource Name": rname or getattr(rec, "impacted_value", "") or "",
                "Resource Type": rtype or getattr(rec, "impacted_field", "") or "",
                "Recommendation": problem,
                "Solution": solution,
                "Potential Savings": _extract_savings(extended),
                "Last Updated": last_updated,
            })
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
    cfg = utils.get_config()
    sub_id = cfg.get("default_subscription_id", "")
    sub_name = utils.get_subscription_name(sub_id)
    if not sub_id:
        print("ERROR: No subscription configured. Run configure.py first.")
        sys.exit(1)
    main(sub_id, sub_name)
