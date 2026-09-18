#!/usr/bin/env python3
"""StratusScanCLI-Azure — Defender for Cloud Secure Score & Plans Export"""

import sys
from pathlib import Path

try:
    import utils
except ImportError:
    sys.path.append(str(Path(__file__).parent.parent))
    import utils

import pandas as pd

log = utils.get_logger()


def _blank_if_none(value):
    return "" if value is None else value


def collect_secure_scores(subscription_id: str) -> list:
    client = utils.get_azure_client("security", subscription_id)
    log.info("Listing secure scores for subscription %s", subscription_id)

    rows = []
    for score in client.secure_scores.list():
        percentage = getattr(score, "percentage", None)
        rows.append({
            "Score Name": getattr(score, "display_name", "") or getattr(score, "name", "") or "",
            "Current Score": _blank_if_none(getattr(score, "current", None)),
            "Max Score": _blank_if_none(getattr(score, "max", None)),
            "Percentage": "" if percentage is None else round(percentage * 100, 2),
            "Weight": _blank_if_none(getattr(score, "weight", None)),
        })
    return rows


def collect_defender_plans(subscription_id: str) -> list:
    client = utils.get_azure_client("security", subscription_id)
    log.info("Listing Defender plans (pricings) for subscription %s", subscription_id)

    rows = []
    result = client.pricings.list(f"subscriptions/{subscription_id}")
    pricings = result.value if hasattr(result, "value") else list(result)
    for p in pricings:
        pricing_tier = utils.s(getattr(p, "pricing_tier", None))
        rows.append({
            "Plan Name": getattr(p, "name", "") or "",
            "Pricing Tier": pricing_tier,
            "Free Trial Remaining": getattr(p, "free_trial_remaining_time", "") or "",
            "Enabled": "Yes" if pricing_tier.lower() == "standard" else "No",
        })
    return rows


def main(subscription_id: str, subscription_name: str) -> utils.ExportResult:
    environment = utils.detect_environment()
    if not utils.is_service_available_in_environment("security", environment):
        sys.exit(0)

    score_rows = collect_secure_scores(subscription_id)
    plan_rows = collect_defender_plans(subscription_id)

    if not score_rows and not plan_rows:
        raise utils.NoResourcesFound("Defender scores or plans")

    sheets = {}
    if score_rows:
        sheets["Secure Scores"] = pd.DataFrame(score_rows)
    if plan_rows:
        sheets["Defender Plans"] = pd.DataFrame(plan_rows)

    filename = utils.create_export_filename(subscription_name, "defender-scores", "all")
    utils.save_multiple_dataframes_to_excel(sheets, filename)
    print(f"Exported {len(score_rows)} score(s), {len(plan_rows)} plan(s) → {filename}")
    log.info("Export complete: %d scores, %d plans", len(score_rows), len(plan_rows))
    return utils.ExportResult(rows=len(score_rows) + len(plan_rows), filename=filename, errors=[])


if __name__ == "__main__":
    import runner

    runner.run_exporter(main, "defender-scores")
