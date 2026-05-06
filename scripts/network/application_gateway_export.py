#!/usr/bin/env python3
"""StratusScanCLI-Azure — Application Gateways Export"""

import sys
from pathlib import Path

try:
    import utils
except ImportError:
    sys.path.append(str(Path(__file__).parent.parent.parent))
    import utils

import pandas as pd

utils.setup_logging("application-gateway-export")
utils.log_script_start("application_gateway_export.py", "Azure Application Gateways Export")

log = utils.get_logger()


def collect_app_gateways(subscription_id: str) -> list:
    client = utils.get_azure_client("network", subscription_id)
    log.info("Listing all application gateways in subscription %s", subscription_id)
    return list(client.application_gateways.list_all())


def main(subscription_id: str, subscription_name: str) -> None:
    environment = utils.detect_environment()
    if not utils.is_service_available_in_environment("network", environment):
        sys.exit(0)

    gateways = collect_app_gateways(subscription_id)
    if not gateways:
        print("No application gateways found.")
        return

    rows = []
    for gw in gateways:
        rg = gw.id.split("/resourceGroups/")[1].split("/")[0] if gw.id else ""
        tags = gw.tags or {}
        rows.append({
            "Name": gw.name,
            "Resource Group": rg,
            "Location": gw.location,
            "SKU Name": gw.sku.name if gw.sku else "",
            "SKU Tier": gw.sku.tier if gw.sku else "",
            "Capacity": gw.sku.capacity if gw.sku else "",
            "WAF Enabled": (
                gw.web_application_firewall_configuration is not None
                and getattr(gw.web_application_firewall_configuration, "enabled", False)
            ),
            "WAF Mode": (
                gw.web_application_firewall_configuration.firewall_mode
                if gw.web_application_firewall_configuration else ""
            ),
            "Frontend IPs": len(gw.frontend_ip_configurations or []),
            "Backend Pools": len(gw.backend_address_pools or []),
            "HTTP Listeners": len(gw.http_listeners or []),
            "Routing Rules": len(gw.request_routing_rules or []),
            "Provisioning State": gw.provisioning_state or "",
            "Tags": "; ".join(f"{k}={v}" for k, v in tags.items()),
        })

    df = pd.DataFrame(rows)
    filename = utils.create_export_filename(subscription_name, "application-gateways", "all")
    utils.save_dataframe_to_excel(df, filename, sheet_name="Application Gateways")
    print(f"Exported {len(rows)} application gateway(s) → {filename}")
    log.info("Export complete: %d application gateways", len(rows))


if __name__ == "__main__":
    cfg = utils.get_config()
    sub_id = cfg.get("default_subscription_id", "")
    sub_name = utils.get_subscription_name(sub_id)
    if not sub_id:
        print("ERROR: No subscription configured. Run configure.py first.")
        sys.exit(1)
    main(sub_id, sub_name)
