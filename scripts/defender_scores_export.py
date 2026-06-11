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

utils.setup_logging("defender-scores-export")
utils.log_script_start("defender_scores_export.py", "Defender Secure Score & Plans Export")

log = utils.get_logger()


def collect_secure_scores(subscription_id: str) -> list:
    client = utils.get_azure_client("security", subscription_id)
    log.info("Listing secure scores for subscription %s", subscription_id)

    rows = []
    try:
        for score in client.secure_scores.list():
            current = 0.0
            max_score = 0.0
            percentage = 0.0
            weight = 0

            if hasattr(score, "score") and score.score:
                current = getattr(score.score, "current", 0.0) or 0.0
                max_score = getattr(score.score, "max", 0.0) or 0.0
                percentage = getattr(score.score, "percentage", 0.0) or 0.0

            if hasattr(score, "weight") and score.weight is not None:
                weight = score.weight

            rows.append({
                "Score Name": getattr(score, "display_name", "") or getattr(score, "name", "") or "",
                "Current Score": current,
                "Max Score": max_score,
                "Percentage": round(percentage * 100, 2) if percentage <= 1.0 else round(percentage, 2),
                "Weight": weight,
            })
    except Exception as e:
        log.warning("Failed to list secure scores: %s", e)

    return rows


def collect_defender_plans(subscription_id: str) -> list:
    client = utils.get_azure_client("security", subscription_id)
    log.info("Listing Defender plans (pricings) for subscription %s", subscription_id)

    rows = []
    try:
        result = client.pricings.list()
        pricings = result.value if hasattr(result, "value") else list(result)
        for p in pricings:
            rows.append({
                "Plan Name": getattr(p, "name", "") or "",
                "Pricing Tier": getattr(p, "pricing_tier", "") or "",
                "Free Trial Remaining": getattr(p, "free_trial_remaining_time", "") or "",
                "Enabled": "Yes" if getattr(p, "pricing_tier", "").lower() == "standard" else "No",
            })
    except Exception as e:
        log.warning("Failed to list Defender plans: %s", e)

    return rows


def main(subscription_id: str, subscription_name: str) -> None:
    environment = utils.detect_environment()
    if not utils.is_service_available_in_environment("resource", environment):
        sys.exit(0)

    score_rows = collect_secure_scores(subscription_id)
    plan_rows = collect_defender_plans(subscription_id)

    if not score_rows and not plan_rows:
        print("No Defender scores or plans found.")
        return

    sheets = {}
    if score_rows:
        sheets["Secure Scores"] = pd.DataFrame(score_rows)
    if plan_rows:
        sheets["Defender Plans"] = pd.DataFrame(plan_rows)

    filename = utils.create_export_filename(subscription_name, "defender-scores", "all")
    utils.save_multiple_dataframes_to_excel(sheets, filename)
    print(f"Exported {len(score_rows)} score(s), {len(plan_rows)} plan(s) → {filename}")
    log.info("Export complete: %d scores, %d plans", len(score_rows), len(plan_rows))


if __name__ == "__main__":
    sub_id, sub_name = utils.resolve_target_subscription()
    if not sub_id:
        print("ERROR: No subscription configured. Run configure.py first.")
        sys.exit(1)
    main(sub_id, sub_name)
