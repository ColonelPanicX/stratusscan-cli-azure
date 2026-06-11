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

utils.setup_logging("vpn-gateways-export")
utils.log_script_start("vpn_gateways_export.py", "VPN Gateways Export")

log = utils.get_logger()


def collect_vpn_gateways(subscription_id: str) -> list:
    network = utils.get_azure_client("network", subscription_id)
    resource = utils.get_azure_client("resource", subscription_id)
    log.info("Listing virtual network gateways across resource groups in %s", subscription_id)

    gateways = []
    for rg in resource.resource_groups.list():
        try:
            for gw in network.virtual_network_gateways.list(rg.name):
                gateways.append((rg.name, gw))
        except Exception as e:
            log.warning("Failed to list gateways in %s: %s", rg.name, e)
    return gateways


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


def main(subscription_id: str, subscription_name: str) -> None:
    environment = utils.detect_environment()
    if not utils.is_service_available_in_environment("network", environment):
        sys.exit(0)

    gateways = collect_vpn_gateways(subscription_id)
    if not gateways:
        print("No VPN gateways found.")
        return

    rows = []
    for rg, gw in gateways:
        tags = gw.tags or {}
        rows.append({
            "Name": gw.name,
            "Resource Group": rg,
            "Location": gw.location,
            "Gateway Type": str(gw.gateway_type) if gw.gateway_type else "",
            "VPN Type": str(gw.vpn_type) if gw.vpn_type else "",
            "SKU": gw.sku.name if gw.sku else "",
            "Generation": str(gw.vpn_gateway_generation) if getattr(gw, "vpn_gateway_generation", None) else "",
            "Active-Active": "Yes" if getattr(gw, "active_active", False) else "No",
            "BGP Enabled": "Yes" if getattr(gw, "enable_bgp", False) else "No",
            "BGP ASN": _bgp_asn(gw),
            "Public IP": _public_ips(gw),
            "Provisioning State": gw.provisioning_state or "",
            "Tags": "; ".join(f"{k}={v}" for k, v in tags.items()),
        })

    df = pd.DataFrame(rows)
    filename = utils.create_export_filename(subscription_name, "vpn-gateways", "all")
    utils.save_dataframe_to_excel(df, filename, sheet_name="VPN Gateways")
    print(f"Exported {len(rows)} VPN gateway(s) → {filename}")
    log.info("Export complete: %d VPN gateways", len(rows))


if __name__ == "__main__":
    sub_id, sub_name = utils.resolve_target_subscription()
    if not sub_id:
        print("ERROR: No subscription configured. Run configure.py first.")
        sys.exit(1)
    main(sub_id, sub_name)
