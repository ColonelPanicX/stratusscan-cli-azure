#!/usr/bin/env python3
"""StratusScanCLI-Azure — Azure Firewall Export"""

import sys
from pathlib import Path

try:
    import utils
except ImportError:
    sys.path.append(str(Path(__file__).parent.parent.parent))
    import utils

import pandas as pd

utils.setup_logging("azure-firewall-export")
utils.log_script_start("azure_firewall_export.py", "Azure Firewall Export")

log = utils.get_logger()


def collect_firewalls(subscription_id: str) -> list:
    client = utils.get_azure_client("network", subscription_id)
    log.info("Listing all Azure Firewalls in subscription %s", subscription_id)
    return list(client.azure_firewalls.list_all())


def main(subscription_id: str, subscription_name: str) -> None:
    environment = utils.detect_environment()
    if not utils.is_service_available_in_environment("network", environment):
        sys.exit(0)

    firewalls = collect_firewalls(subscription_id)
    if not firewalls:
        print("No Azure Firewalls found.")
        return

    rows = []
    for fw in firewalls:
        rg = utils.extract_resource_group(fw.id)
        tags = fw.tags or {}
        policy_id = ""
        if fw.firewall_policy and fw.firewall_policy.id:
            policy_id = fw.firewall_policy.id.split("/")[-1]
        rows.append({
            "Name": fw.name,
            "Resource Group": rg,
            "Location": fw.location,
            "SKU Name": fw.sku.name if fw.sku else "",
            "SKU Tier": fw.sku.tier if fw.sku else "",
            "Threat Intel Mode": str(fw.threat_intel_mode) if fw.threat_intel_mode else "",
            "Firewall Policy": policy_id,
            "Network Rule Collections": len(fw.network_rule_collections or []),
            "Application Rule Collections": len(fw.application_rule_collections or []),
            "NAT Rule Collections": len(fw.nat_rule_collections or []),
            "Provisioning State": fw.provisioning_state or "",
            "Tags": "; ".join(f"{k}={v}" for k, v in tags.items()),
        })

    df = pd.DataFrame(rows)
    filename = utils.create_export_filename(subscription_name, "azure-firewalls", "all")
    utils.save_dataframe_to_excel(df, filename, sheet_name="Azure Firewalls")
    print(f"Exported {len(rows)} Azure Firewall(s) → {filename}")
    log.info("Export complete: %d firewalls", len(rows))


if __name__ == "__main__":
    sub_id, sub_name = utils.resolve_target_subscription()
    if not sub_id:
        print("ERROR: No subscription configured. Run configure.py first.")
        sys.exit(1)
    main(sub_id, sub_name)
