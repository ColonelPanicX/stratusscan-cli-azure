#!/usr/bin/env python3
"""StratusScanCLI-Azure — Application Gateways Export"""

import sys
from pathlib import Path

try:
    import utils
except ImportError:
    sys.path.append(str(Path(__file__).parent.parent))
    import utils

import pandas as pd
from azure.core.exceptions import HttpResponseError

log = utils.get_logger()


def collect_app_gateways(client) -> list:
    log.info("Listing all application gateways")
    return list(client.application_gateways.list_all())


def collect_waf_policies(client) -> dict:
    """One subscription-wide list; keyed by lower-cased policy resource ID."""
    try:
        policies = list(client.web_application_firewall_policies.list_all())
    except HttpResponseError as e:
        log.warning("WAF policies unavailable; policy-based WAF columns left blank: %s", e.message)
        return {}
    return {p.id.lower(): p for p in policies if p.id}


def _policy_id(gw) -> str:
    return gw.firewall_policy.id if gw.firewall_policy and gw.firewall_policy.id else ""


def _listener_policy_count(gw) -> int:
    return sum(
        1 for listener in (gw.http_listeners or [])
        if listener.firewall_policy and listener.firewall_policy.id
    )


def _waf_columns(gw, policies: dict) -> dict:
    legacy = gw.web_application_firewall_configuration
    policy_id = _policy_id(gw)
    listener_policies = _listener_policy_count(gw)
    policy = policies.get(policy_id.lower()) if policy_id else None
    settings = policy.policy_settings if policy else None

    if policy_id:
        source = "Policy"
        mode = utils.s(settings.mode) if settings else ""
        state = utils.s(settings.state) if settings else ""
    elif legacy is not None:
        source = "Legacy Config"
        mode = utils.s(legacy.firewall_mode)
        state = "Enabled" if legacy.enabled else "Disabled"
    else:
        source = ""
        mode = ""
        state = ""

    enabled = bool(policy_id) or listener_policies > 0 or bool(legacy is not None and legacy.enabled)
    return {
        "WAF Enabled": enabled,
        "WAF Mode": mode,
        "WAF State": state,
        "WAF Policy": policy_id.split("/")[-1] if policy_id else "",
        "WAF Source": source,
        "Listener WAF Policies": listener_policies,
    }


def _build_row(gw, policies: dict) -> dict:
    tags = gw.tags or {}
    sku = gw.sku
    ssl = gw.ssl_policy
    waf = _waf_columns(gw, policies)
    return {
        "Name": gw.name,
        "Resource Group": utils.extract_resource_group(gw.id),
        "Location": gw.location,
        "SKU Name": utils.s(sku.name) if sku else "",
        "SKU Tier": utils.s(sku.tier) if sku else "",
        "Capacity": sku.capacity if sku and sku.capacity is not None else "",
        "WAF Enabled": waf["WAF Enabled"],
        "WAF Mode": waf["WAF Mode"],
        "Frontend IPs": len(gw.frontend_ip_configurations or []),
        "Backend Pools": len(gw.backend_address_pools or []),
        "HTTP Listeners": len(gw.http_listeners or []),
        "Routing Rules": len(gw.request_routing_rules or []),
        "Provisioning State": utils.s(gw.provisioning_state),
        "Tags": "; ".join(f"{k}={v}" for k, v in tags.items()),
        "WAF State": waf["WAF State"],
        "WAF Policy": waf["WAF Policy"],
        "WAF Source": waf["WAF Source"],
        "Listener WAF Policies": waf["Listener WAF Policies"],
        "SSL Policy Type": utils.s(ssl.policy_type) if ssl else "",
        "SSL Policy Name": utils.s(ssl.policy_name) if ssl else "",
        "SSL Min Protocol Version": utils.s(ssl.min_protocol_version) if ssl else "",
        "HTTP/2 Enabled": "" if gw.enable_http2 is None else gw.enable_http2,
        "Zones": ", ".join(gw.zones) if gw.zones else "",
    }


def main(subscription_id: str, subscription_name: str) -> utils.ExportResult:
    environment = utils.detect_environment()
    if not utils.is_service_available_in_environment("network", environment):
        sys.exit(0)

    client = utils.get_azure_client("network", subscription_id)
    gateways = collect_app_gateways(client)
    if not gateways:
        raise utils.NoResourcesFound("application gateways")

    policies = collect_waf_policies(client)
    rows = [_build_row(gw, policies) for gw in gateways]

    df = pd.DataFrame(rows)
    filename = utils.create_export_filename(subscription_name, "application-gateways", "all")
    utils.save_dataframe_to_excel(df, filename, sheet_name="Application Gateways")
    print(f"Exported {len(rows)} application gateway(s) → {filename}")
    log.info("Export complete: %d application gateways", len(rows))
    return utils.ExportResult(rows=len(rows), filename=filename, errors=[])


if __name__ == "__main__":
    import runner

    runner.run_exporter(main, "application-gateway")
