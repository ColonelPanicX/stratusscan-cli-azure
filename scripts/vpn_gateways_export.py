#!/usr/bin/env python3
"""StratusScanCLI-Azure — VPN Gateways Export"""

import sys
from pathlib import Path

try:
    import utils
except ImportError:
    sys.path.append(str(Path(__file__).parent.parent))
    import utils

import pandas as pd
from azure.core.exceptions import HttpResponseError

utils.setup_logging("vpn-gateways-export")
utils.log_script_start("vpn_gateways_export.py", "VPN Gateways Export")

log = utils.get_logger()


def collect_vpn_gateways(subscription_id: str) -> tuple:
    """Return ([(resource_group, gateway)], errors); a resource group whose listing fails is recorded, not dropped."""
    network = utils.get_azure_client("network", subscription_id)
    resource = utils.get_azure_client("resource", subscription_id)
    log.info("Listing virtual network gateways across resource groups in %s", subscription_id)

    gateways = []
    errors: list = []
    for rg in resource.resource_groups.list():
        try:
            for gw in network.virtual_network_gateways.list(rg.name):
                gateways.append((rg.name, gw))
        except HttpResponseError as e:
            errors.append(utils.error_record(rg.name, "virtual_network_gateways.list", e))
            log.warning("Failed to list gateways in %s: %s", rg.name, e)
    return gateways, errors


def _public_ips(gw) -> str:
    names = []
    for cfg in getattr(gw, "ip_configurations", None) or []:
        pip_id = getattr(getattr(cfg, "public_ip_address", None), "id", "") or ""
        if pip_id:
            names.append(pip_id.split("/")[-1])
    return ", ".join(names)


def _bgp_asn(gw) -> str:
    try:
        if gw.bgp_settings and gw.bgp_settings.asn is not None:
            return str(gw.bgp_settings.asn)
    except Exception:
        pass
    return ""


def main(subscription_id: str, subscription_name: str) -> utils.ExportResult:
    environment = utils.detect_environment()
    if not utils.is_service_available_in_environment("network", environment):
        sys.exit(0)

    gateways, errors = collect_vpn_gateways(subscription_id)
    if not gateways and not errors:
        raise utils.NoResourcesFound("VPN gateways")

    rows = []
    for rg, gw in gateways:
        tags = gw.tags or {}
        rows.append({
            "Name": gw.name,
            "Resource Group": rg,
            "Location": gw.location,
            "Gateway Type": utils.s(gw.gateway_type),
            "VPN Type": utils.s(gw.vpn_type),
            "SKU": gw.sku.name if gw.sku else "",
            "Generation": utils.s(gw.vpn_gateway_generation) if getattr(gw, "vpn_gateway_generation", None) else "",
            "Active-Active": "Yes" if getattr(gw, "active_active", False) else "No",
            "BGP Enabled": "Yes" if getattr(gw, "enable_bgp", False) else "No",
            "BGP ASN": _bgp_asn(gw),
            "Public IP": _public_ips(gw),
            "Provisioning State": gw.provisioning_state or "",
            "Tags": "; ".join(f"{k}={v}" for k, v in tags.items()),
        })

    df = pd.DataFrame(rows)
    filename = utils.create_export_filename(subscription_name, "vpn-gateways", "all")
    utils.save_dataframe_to_excel(df, filename, sheet_name="VPN Gateways", errors=errors)
    print(f"Exported {len(rows)} VPN gateway(s) → {filename}")
    log.info("Export complete: %d VPN gateways", len(rows))
    return utils.ExportResult(rows=len(rows), filename=filename, errors=errors)


if __name__ == "__main__":
    import runner

    runner.run_exporter(main, "vpn-gateways")
