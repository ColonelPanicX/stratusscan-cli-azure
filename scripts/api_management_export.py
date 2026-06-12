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

utils.setup_logging("api-management-export")
utils.log_script_start("api_management_export.py", "API Management Services Export")

log = utils.get_logger()


def collect_services(subscription_id: str) -> list:
    client = utils.get_azure_client("apimanagement", subscription_id)
    log.info("Listing API Management services in subscription %s", subscription_id)
    if hasattr(client.api_management_service, "list"):
        return list(client.api_management_service.list())

    resource = utils.get_azure_client("resource", subscription_id)
    services = []
    for rg in resource.resource_groups.list():
        try:
            services.extend(client.api_management_service.list_by_resource_group(rg.name))
        except Exception as exc:
            log.warning("Failed to list API Management services in %s: %s", rg.name, exc)
    return services


def main(subscription_id: str, subscription_name: str) -> None:
    environment = utils.detect_environment()
    if not utils.is_service_available_in_environment("apimanagement", environment):
        sys.exit(0)

    services = collect_services(subscription_id)
    if not services:
        print("No API Management services found.")
        return

    rows = []
    for svc in services:
        sku = svc.sku
        tags = svc.tags or {}
        rows.append({
            "Name": svc.name,
            "Resource Group": utils.extract_resource_group(svc.id),
            "Location": svc.location,
            "SKU": str(sku.name) if sku else "",
            "Capacity": getattr(sku, "capacity", "") if sku else "",
            "Publisher Name": svc.publisher_name or "",
            "Publisher Email": svc.publisher_email or "",
            "Gateway URL": svc.gateway_url or "",
            "Provisioning State": svc.provisioning_state or "",
            "VNet Type": str(svc.virtual_network_type) if svc.virtual_network_type else "",
            "Tags": "; ".join(f"{k}={v}" for k, v in tags.items()),
        })

    df = pd.DataFrame(rows)
    filename = utils.create_export_filename(subscription_name, "api-management", "all")
    utils.save_dataframe_to_excel(df, filename, sheet_name="API Management")
    print(f"Exported {len(rows)} API Management service(s) → {filename}")
    log.info("Export complete: %d services", len(rows))


if __name__ == "__main__":
    sub_id, sub_name = utils.resolve_target_subscription()
    if not sub_id:
        print("ERROR: No subscription configured. Run configure.py first.")
        sys.exit(1)
    main(sub_id, sub_name)
