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
from azure.core.exceptions import HttpResponseError

utils.setup_logging("api-management-export")
utils.log_script_start("api_management_export.py", "API Management Services Export")

log = utils.get_logger()


def collect_services(subscription_id: str) -> tuple:
    client = utils.get_azure_client("apimanagement", subscription_id)
    log.info("Listing API Management services in subscription %s", subscription_id)
    if hasattr(client.api_management_service, "list"):
        return list(client.api_management_service.list()), []

    resource = utils.get_azure_client("resource", subscription_id)
    services = []
    errors: list = []
    for rg in resource.resource_groups.list():
        try:
            services.extend(client.api_management_service.list_by_resource_group(rg.name))
        except HttpResponseError as exc:
            errors.append(utils.error_record(rg.name, "api_management_service.list_by_resource_group", exc))
            log.warning("Failed to list API Management services in %s: %s", rg.name, exc)
    return services, errors


def main(subscription_id: str, subscription_name: str) -> utils.ExportResult:
    environment = utils.detect_environment()
    if not utils.is_service_available_in_environment("apimanagement", environment):
        sys.exit(0)

    services, errors = collect_services(subscription_id)
    if not services and not errors:
        raise utils.NoResourcesFound("API Management services")

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
