#!/usr/bin/env python3
"""StratusScanCLI-Azure — API Management Services Export"""

import sys
from pathlib import Path

try:
    import utils
except ImportError:
    sys.path.append(str(Path(__file__).parent.parent))
    import utils

import pandas as pd

log = utils.get_logger()


def collect_services(subscription_id: str) -> list:
    client = utils.get_azure_client("apimanagement", subscription_id)
    log.info("Listing API Management services in subscription %s", subscription_id)
    return list(
        utils.list_subscription_wide(client.api_management_service, "list", "list_by_subscription")
    )


def main(subscription_id: str, subscription_name: str) -> utils.ExportResult:
    environment = utils.detect_environment()
    if not utils.is_service_available_in_environment("apimanagement", environment):
        sys.exit(0)

    services = collect_services(subscription_id)
    if not services:
        raise utils.NoResourcesFound("API Management services")

    errors: list = []
    rows = []
    for svc in services:
        sku = svc.sku
        tags = svc.tags or {}
        rows.append({
            "Name": svc.name,
            "Resource Group": utils.extract_resource_group(svc.id),
            "Location": svc.location,
            "SKU": utils.s(sku.name) if sku else "",
            "Capacity": getattr(sku, "capacity", "") if sku else "",
            "Publisher Name": svc.publisher_name or "",
            "Publisher Email": svc.publisher_email or "",
            "Gateway URL": svc.gateway_url or "",
            "Provisioning State": svc.provisioning_state or "",
            "VNet Type": utils.s(svc.virtual_network_type),
            "Tags": "; ".join(f"{k}={v}" for k, v in tags.items()),
        })

    df = pd.DataFrame(rows)
    filename = utils.create_export_filename(subscription_name, "api-management", "all")
    utils.save_dataframe_to_excel(df, filename, sheet_name="API Management", errors=errors)
    print(f"Exported {len(rows)} API Management service(s) → {filename}")
    log.info("Export complete: %d services", len(rows))
    return utils.ExportResult(rows=len(rows), filename=filename, errors=errors)


if __name__ == "__main__":
    import runner

    runner.run_exporter(main, "api-management")
