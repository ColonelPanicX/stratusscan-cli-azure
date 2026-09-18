#!/usr/bin/env python3
"""StratusScanCLI-Azure — ExpressRoute Circuits Export"""

import sys
from pathlib import Path

try:
    import utils
except ImportError:
    sys.path.append(str(Path(__file__).parent.parent))
    import utils

import pandas as pd

log = utils.get_logger()


def collect_circuits(subscription_id: str) -> list:
    client = utils.get_azure_client("network", subscription_id)
    log.info("Listing all ExpressRoute circuits in subscription %s", subscription_id)
    return list(client.express_route_circuits.list_all())


def main(subscription_id: str, subscription_name: str) -> utils.ExportResult:
    environment = utils.detect_environment()
    if not utils.is_service_available_in_environment("network", environment):
        sys.exit(0)

    circuits = collect_circuits(subscription_id)
    if not circuits:
        raise utils.NoResourcesFound("ExpressRoute circuits")

    rows = []
    for c in circuits:
        rg = utils.extract_resource_group(c.id)
        provider = getattr(c, "service_provider_properties", None)
        tags = c.tags or {}
        rows.append({
            "Name": c.name,
            "Resource Group": rg,
            "Location": c.location,
            "SKU Name": c.sku.name if c.sku else "",
            "SKU Tier": c.sku.tier if c.sku else "",
            "SKU Family": c.sku.family if c.sku else "",
            "Service Provider": getattr(provider, "service_provider_name", "") or "" if provider else "",
            "Peering Location": getattr(provider, "peering_location", "") or "" if provider else "",
            "Bandwidth Mbps": getattr(provider, "bandwidth_in_mbps", "") if provider else "",
            "Circuit State": getattr(c, "circuit_provisioning_state", "") or "",
            "Provisioning State": c.provisioning_state or "",
            "Allow Classic Operations": "Yes" if getattr(c, "allow_classic_operations", False) else "No",
            "Tags": "; ".join(f"{k}={v}" for k, v in tags.items()),
        })

    df = pd.DataFrame(rows)
    filename = utils.create_export_filename(subscription_name, "expressroute", "all")
    utils.save_dataframe_to_excel(df, filename, sheet_name="ExpressRoute Circuits")
    print(f"Exported {len(rows)} ExpressRoute circuit(s) → {filename}")
    log.info("Export complete: %d circuits", len(rows))
    return utils.ExportResult(rows=len(rows), filename=filename, errors=[])


if __name__ == "__main__":
    import runner

    runner.run_exporter(main, "expressroute")
