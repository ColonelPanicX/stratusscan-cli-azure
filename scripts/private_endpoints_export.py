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

log = utils.get_logger()


def collect_private_endpoints(subscription_id: str) -> list:
    client = utils.get_azure_client("network", subscription_id)
    log.info("Listing all private endpoints in subscription %s", subscription_id)
    return list(client.private_endpoints.list_by_subscription())


def _connections(pe) -> list:
    return list(pe.private_link_service_connections or []) + list(
        pe.manual_private_link_service_connections or []
    )


def _target_resource(pe) -> str:
    names = []
    for c in _connections(pe):
        svc_id = c.private_link_service_id or ""
        if svc_id:
            names.append(svc_id.split("/")[-1])
    return ", ".join(names)


def _target_subresource(pe) -> str:
    groups = []
    for c in _connections(pe):
        groups.extend(c.group_ids or [])
    return ", ".join(groups)


def _connection_status(pe) -> str:
    statuses = []
    for c in _connections(pe):
        state = c.private_link_service_connection_state
        if state and state.status:
            statuses.append(utils.s(state.status))
    return ", ".join(statuses)


def _custom_dns(pe) -> str:
    return ", ".join(cfg.fqdn for cfg in (pe.custom_dns_configs or []) if cfg.fqdn)


def main(subscription_id: str, subscription_name: str) -> utils.ExportResult:
    environment = utils.detect_environment()
    if not utils.is_service_available_in_environment("network", environment):
        sys.exit(0)

    endpoints = collect_private_endpoints(subscription_id)
    if not endpoints:
        raise utils.NoResourcesFound("private endpoints")

    rows = []
    for pe in endpoints:
        subnet_id = pe.subnet.id if pe.subnet and pe.subnet.id else ""
        tags = pe.tags or {}
        rows.append({
            "Name": pe.name,
            "Resource Group": utils.extract_resource_group(pe.id),
            "Location": pe.location,
            "Subnet": subnet_id.split("/")[-1] if subnet_id else "",
            "Target Resource": _target_resource(pe),
            "Target Sub-Resource": _target_subresource(pe),
            "Connection Status": _connection_status(pe),
            "Provisioning State": utils.s(pe.provisioning_state),
            "Custom DNS Configs": _custom_dns(pe),
            "Tags": "; ".join(f"{k}={v}" for k, v in tags.items()),
        })

    df = pd.DataFrame(rows)
    filename = utils.create_export_filename(subscription_name, "private-endpoints", "all")
    utils.save_dataframe_to_excel(df, filename, sheet_name="Private Endpoints")
    print(f"Exported {len(rows)} private endpoint(s) → {filename}")
    log.info("Export complete: %d private endpoints", len(rows))
    return utils.ExportResult(rows=len(rows), filename=filename, errors=[])


if __name__ == "__main__":
    import runner

    runner.run_exporter(main, "private-endpoints")
