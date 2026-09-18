#!/usr/bin/env python3
"""StratusScanCLI-Azure — DNS Zones Export (public + private)"""

import sys
from pathlib import Path

try:
    import utils
except ImportError:
    sys.path.append(str(Path(__file__).parent.parent))
    import utils

import pandas as pd

log = utils.get_logger()


def collect_public_zones(subscription_id: str) -> list:
    client = utils.get_azure_client("dns", subscription_id)
    log.info("Listing public DNS zones in subscription %s", subscription_id)
    return list(client.zones.list())


def collect_private_zones(subscription_id: str) -> list:
    client = utils.get_azure_client("privatedns", subscription_id)
    log.info("Listing private DNS zones in subscription %s", subscription_id)
    return list(client.private_zones.list())


def _public_rows(zones: list) -> list:
    rows = []
    for zone in zones:
        tags = zone.tags or {}
        rows.append({
            "Name": zone.name,
            "Resource Group": utils.extract_resource_group(zone.id),
            "Type": utils.s(zone.zone_type) if getattr(zone, "zone_type", None) else "Public",
            "Record Sets": zone.number_of_record_sets if zone.number_of_record_sets is not None else "",
            "Max Record Sets": zone.max_number_of_record_sets if zone.max_number_of_record_sets is not None else "",
            "Name Servers": ", ".join(zone.name_servers) if zone.name_servers else "",
            "Tags": "; ".join(f"{k}={v}" for k, v in tags.items()),
        })
    return rows


def _private_rows(zones: list) -> list:
    rows = []
    for zone in zones:
        tags = zone.tags or {}
        rows.append({
            "Name": zone.name,
            "Resource Group": utils.extract_resource_group(zone.id),
            "Record Sets": zone.number_of_record_sets if zone.number_of_record_sets is not None else "",
            "VNet Links": zone.number_of_virtual_network_links if zone.number_of_virtual_network_links is not None else "",
            "VNet Links w/ Registration": zone.number_of_virtual_network_links_with_registration
            if zone.number_of_virtual_network_links_with_registration is not None else "",
            "Provisioning State": zone.provisioning_state or "",
            "Tags": "; ".join(f"{k}={v}" for k, v in tags.items()),
        })
    return rows


def main(subscription_id: str, subscription_name: str) -> utils.ExportResult:
    environment = utils.detect_environment()
    if not utils.is_service_available_in_environment("dns", environment):
        sys.exit(0)

    public = _public_rows(collect_public_zones(subscription_id))
    private = _private_rows(collect_private_zones(subscription_id))

    if not public and not private:
        raise utils.NoResourcesFound("DNS zones")

    sheets = {}
    if public:
        sheets["Public Zones"] = pd.DataFrame(public)
    if private:
        sheets["Private Zones"] = pd.DataFrame(private)

    filename = utils.create_export_filename(subscription_name, "dns-zones", "all")
    utils.save_multiple_dataframes_to_excel(sheets, filename)
    print(f"Exported {len(public)} public + {len(private)} private DNS zone(s) → {filename}")
    log.info("Export complete: %d public, %d private", len(public), len(private))
    return utils.ExportResult(rows=len(public) + len(private), filename=filename, errors=[])


if __name__ == "__main__":
    import runner

    runner.run_exporter(main, "dns-zones")
