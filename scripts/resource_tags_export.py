#!/usr/bin/env python3
"""StratusScanCLI-Azure — Resource Tags Inventory Export"""

import sys
from collections import defaultdict
from pathlib import Path

try:
    import utils
except ImportError:
    sys.path.append(str(Path(__file__).parent.parent))
    import utils

import pandas as pd

utils.setup_logging("resource-tags-export")
utils.log_script_start("resource_tags_export.py", "Resource Tags Inventory Export")

log = utils.get_logger()


def collect_resources(subscription_id: str) -> list:
    client = utils.get_azure_client("resource", subscription_id)
    log.info("Listing all resources in subscription %s", subscription_id)
    return list(client.resources.list())


def main(subscription_id: str, subscription_name: str) -> None:
    environment = utils.detect_environment()
    if not utils.is_service_available_in_environment("resource", environment):
        sys.exit(0)

    resources = collect_resources(subscription_id)
    if not resources:
        print("No resources found.")
        return

    coverage_rows = []
    key_counts = defaultdict(int)
    key_values = defaultdict(set)

    for r in resources:
        rg = r.id.split("/resourceGroups/")[1].split("/")[0] if r.id and "/resourceGroups/" in r.id else ""
        tags = r.tags or {}
        for k, v in tags.items():
            key_counts[k] += 1
            key_values[k].add(v)
        coverage_rows.append({
            "Resource Name": r.name,
            "Resource Type": r.type,
            "Resource Group": rg,
            "Location": getattr(r, "location", "") or "",
            "Tag Count": len(tags),
            "Tagged": "Yes" if tags else "No",
            "Tags": "; ".join(f"{k}={v}" for k, v in tags.items()),
        })

    key_rows = [
        {
            "Tag Key": k,
            "Resource Count": key_counts[k],
            "Distinct Values": len(key_values[k]),
            "Sample Values": ", ".join(sorted(str(v) for v in key_values[k])[:10]),
        }
        for k in sorted(key_counts)
    ]

    sheets = {"Tag Coverage": pd.DataFrame(coverage_rows)}
    if key_rows:
        sheets["Tag Keys"] = pd.DataFrame(key_rows)

    filename = utils.create_export_filename(subscription_name, "resource-tags", "all")
    utils.save_multiple_dataframes_to_excel(sheets, filename)
    tagged = sum(1 for row in coverage_rows if row["Tagged"] == "Yes")
    print(f"Exported {len(coverage_rows)} resource(s), {tagged} tagged, {len(key_rows)} unique tag key(s) → {filename}")
    log.info("Export complete: %d resources, %d tag keys", len(coverage_rows), len(key_rows))


if __name__ == "__main__":
    cfg = utils.get_config()
    sub_id = cfg.get("default_subscription_id", "")
    sub_name = utils.get_subscription_name(sub_id)
    if not sub_id:
        print("ERROR: No subscription configured. Run configure.py first.")
        sys.exit(1)
    main(sub_id, sub_name)
