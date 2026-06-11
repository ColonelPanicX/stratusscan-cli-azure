#!/usr/bin/env python3
"""StratusScanCLI-Azure — DDoS Protection Plans Export"""

import sys
from pathlib import Path

try:
    import utils
except ImportError:
    sys.path.append(str(Path(__file__).parent.parent))
    import utils

import pandas as pd

utils.setup_logging("ddos-protection-export")
utils.log_script_start("ddos_protection_export.py", "DDoS Protection Plans Export")

log = utils.get_logger()


def collect_plans(subscription_id: str) -> list:
    client = utils.get_azure_client("network", subscription_id)
    log.info("Listing all DDoS protection plans in subscription %s", subscription_id)
    return list(client.ddos_protection_plans.list())


def main(subscription_id: str, subscription_name: str) -> None:
    environment = utils.detect_environment()
    if not utils.is_service_available_in_environment("network", environment):
        sys.exit(0)

    plans = collect_plans(subscription_id)
    if not plans:
        print("No DDoS protection plans found.")
        return

    rows = []
    for plan in plans:
        rg = plan.id.split("/resourceGroups/")[1].split("/")[0] if plan.id else ""
        vnets = [v.id.split("/")[-1] for v in (getattr(plan, "virtual_networks", None) or []) if getattr(v, "id", "")]
        tags = plan.tags or {}
        rows.append({
            "Name": plan.name,
            "Resource Group": rg,
            "Location": plan.location,
            "Provisioning State": plan.provisioning_state or "",
            "Associated VNet Count": len(vnets),
            "Associated VNets": ", ".join(vnets),
            "Tags": "; ".join(f"{k}={v}" for k, v in tags.items()),
        })

    df = pd.DataFrame(rows)
    filename = utils.create_export_filename(subscription_name, "ddos-protection", "all")
    utils.save_dataframe_to_excel(df, filename, sheet_name="DDoS Protection Plans")
    print(f"Exported {len(rows)} DDoS protection plan(s) → {filename}")
    log.info("Export complete: %d plans", len(rows))


if __name__ == "__main__":
    sub_id, sub_name = utils.resolve_target_subscription()
    if not sub_id:
        print("ERROR: No subscription configured. Run configure.py first.")
        sys.exit(1)
    main(sub_id, sub_name)
