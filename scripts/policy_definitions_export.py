#!/usr/bin/env python3
"""StratusScanCLI-Azure — Custom Policy Definitions Export"""

import sys
from pathlib import Path

try:
    import utils
except ImportError:
    sys.path.append(str(Path(__file__).parent.parent))
    import utils

import pandas as pd

utils.setup_logging("policy-definitions-export")
utils.log_script_start("policy_definitions_export.py", "Custom Policy Definitions Export")

log = utils.get_logger()


def collect_definitions(subscription_id: str) -> list:
    client = utils.get_azure_client("policy", subscription_id)
    log.info("Listing custom policy definitions in subscription %s", subscription_id)
    return [d for d in client.policy_definitions.list() if str(getattr(d, "policy_type", "")) == "Custom"]


def _metadata_value(definition, key: str) -> str:
    metadata = getattr(definition, "metadata", None) or {}
    if isinstance(metadata, dict):
        return str(metadata.get(key, "") or "")
    return ""


def _effect(definition) -> str:
    try:
        rule = getattr(definition, "policy_rule", None) or {}
        then = rule.get("then", {}) if isinstance(rule, dict) else {}
        return str(then.get("effect", "") or "")
    except Exception:
        return ""


def main(subscription_id: str, subscription_name: str) -> None:
    environment = utils.detect_environment()
    if not utils.is_service_available_in_environment("policy", environment):
        sys.exit(0)

    definitions = collect_definitions(subscription_id)
    if not definitions:
        print("No custom policy definitions found.")
        return

    rows = []
    for d in definitions:
        params = getattr(d, "parameters", None) or {}
        rows.append({
            "Name": d.name or "",
            "Display Name": getattr(d, "display_name", "") or "",
            "Description": getattr(d, "description", "") or "",
            "Policy Type": str(getattr(d, "policy_type", "")) or "",
            "Mode": getattr(d, "mode", "") or "",
            "Category": _metadata_value(d, "category"),
            "Effect": _effect(d),
            "Parameter Count": len(params),
            "Version": _metadata_value(d, "version"),
            "Created By": _metadata_value(d, "createdBy"),
            "Created Date": _metadata_value(d, "createdOn"),
        })

    df = pd.DataFrame(rows)
    filename = utils.create_export_filename(subscription_name, "policy-definitions", "custom")
    utils.save_dataframe_to_excel(df, filename, sheet_name="Custom Policy Definitions")
    print(f"Exported {len(rows)} custom policy definition(s) → {filename}")
    log.info("Export complete: %d custom policy definitions", len(rows))


if __name__ == "__main__":
    sub_id, sub_name = utils.resolve_target_subscription()
    if not sub_id:
        print("ERROR: No subscription configured. Run configure.py first.")
        sys.exit(1)
    main(sub_id, sub_name)
