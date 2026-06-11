#!/usr/bin/env python3
"""StratusScanCLI-Azure — Private Endpoints Export"""

import sys
from pathlib import Path

try:
    import utils
except ImportError:
    sys.path.append(str(Path(__file__).parent.parent))
    import utils

import pandas as pd

utils.setup_logging("private-endpoints-export")
utils.log_script_start("private_endpoints_export.py", "Private Endpoints Export")

log = utils.get_logger()


def collect_private_endpoints(subscription_id: str) -> list:
    client = utils.get_azure_client("network", subscription_id)
    log.info("Listing all private endpoints in subscription %s", subscription_id)
    return list(client.private_endpoints.list_by_subscription())


def _connections(pe):
    conns = getattr(pe, "private_link_service_connections", None) or []
    conns += getattr(pe, "manual_private_link_service_connections", None) or []
    return conns


def _target_resource(pe) -> str:
    names = []
    for c in _connections(pe):
        svc_id = getattr(c, "private_link_service_id", "") or ""
        if svc_id:
            names.append(svc_id.split("/")[-1])
    return ", ".join(names)


def _target_subresource(pe) -> str:
    groups = []
    for c in _connections(pe):
        groups.extend(getattr(c, "group_ids", None) or [])
    return ", ".join(groups)


def _connection_status(pe) -> str:
    statuses = []
    for c in _connections(pe):
        state = getattr(c, "private_link_service_connection_state", None)
        if state and getattr(state, "status", None):
            statuses.append(state.status)
    return ", ".join(statuses)


def _custom_dns(pe) -> str:
    fqdns = []
    for cfg in getattr(pe, "custom_dns_configs", None) or []:
        fqdn = getattr(cfg, "fqdn", "") or ""
        if fqdn:
            fqdns.append(fqdn)
    return ", ".join(fqdns)


def main(subscription_id: str, subscription_name: str) -> None:
    environment = utils.detect_environment()
    if not utils.is_service_available_in_environment("network", environment):
        sys.exit(0)

    endpoints = collect_private_endpoints(subscription_id)
    if not endpoints:
        print("No private endpoints found.")
        return

    rows = []
    for pe in endpoints:
        rg = pe.id.split("/resourceGroups/")[1].split("/")[0] if pe.id else ""
        subnet_id = getattr(getattr(pe, "subnet", None), "id", "") or ""
        subnet = subnet_id.split("/")[-1] if subnet_id else ""
        tags = pe.tags or {}
        rows.append({
            "Name": pe.name,
            "Resource Group": rg,
            "Location": pe.location,
            "Subnet": subnet,
            "Target Resource": _target_resource(pe),
            "Target Sub-Resource": _target_subresource(pe),
            "Connection Status": _connection_status(pe),
            "Provisioning State": pe.provisioning_state or "",
            "Custom DNS Configs": _custom_dns(pe),
            "Tags": "; ".join(f"{k}={v}" for k, v in tags.items()),
        })

    df = pd.DataFrame(rows)
    filename = utils.create_export_filename(subscription_name, "private-endpoints", "all")
    utils.save_dataframe_to_excel(df, filename, sheet_name="Private Endpoints")
    print(f"Exported {len(rows)} private endpoint(s) → {filename}")
    log.info("Export complete: %d private endpoints", len(rows))


if __name__ == "__main__":
    sub_id, sub_name = utils.resolve_target_subscription()
    if not sub_id:
        print("ERROR: No subscription configured. Run configure.py first.")
        sys.exit(1)
    main(sub_id, sub_name)
