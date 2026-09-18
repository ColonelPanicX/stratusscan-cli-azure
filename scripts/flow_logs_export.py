#!/usr/bin/env python3
"""StratusScanCLI-Azure — Network Watcher Flow Logs Export

Flow logs are child resources of a Network Watcher, so they are listed per
watcher; a watcher that answers an error is recorded on the Errors sheet
(PARTIAL) and the run continues.

NSG flow logs retire on 30 September 2027 and cannot be created any more;
virtual network flow logs (target: a virtual network, subnet or network
interface) replace them. Both kinds come back from the same listing, so the
Flow Log Type column is derived from the target resource type. The Coverage
sheet names the NSGs and VNets in the subscription that no flow log targets.
"""

import sys
from pathlib import Path
from typing import Any

try:
    import utils
except ImportError:
    sys.path.append(str(Path(__file__).parent.parent))
    import utils

import pandas as pd
from azure.core.exceptions import HttpResponseError

log = utils.get_logger()

NSG_TARGET_TYPE = "microsoft.network/networksecuritygroups"
VNET_FLOW_LOG_TARGET_TYPES = (
    "microsoft.network/virtualnetworks",
    "microsoft.network/virtualnetworks/subnets",
    "microsoft.network/networkinterfaces",
)

FLOW_LOG_COLUMNS = [
    "Name", "Resource Group", "Network Watcher", "Location", "Flow Log Type",
    "Target Resource ID", "Target Type", "Target Name", "Enabled",
    "Storage Account ID", "Retention Days", "Retention Enabled",
    "Format", "Format Version", "Traffic Analytics Enabled",
    "Traffic Analytics Workspace", "Traffic Analytics Workspace Region",
    "Traffic Analytics Interval (min)", "Provisioning State",
]
COVERAGE_COLUMNS = ["Resource Type", "Name", "Resource Group", "Flow Log", "Flow Log Target"]


def _resource_type_from_id(resource_id: str) -> str:
    parts = [p for p in resource_id.split("/") if p]
    lowered = [p.lower() for p in parts]
    if "providers" not in lowered:
        return ""
    p = len(lowered) - 1 - lowered[::-1].index("providers")
    if p + 1 >= len(parts):
        return ""
    return "/".join([parts[p + 1]] + parts[p + 2::2])


def flow_log_type(target_type: str) -> str:
    lowered = target_type.lower()
    if lowered == NSG_TARGET_TYPE:
        return "NSG (retires 09.30.2027)"
    if lowered in VNET_FLOW_LOG_TARGET_TYPES:
        return "VNet"
    return ""


def collect_watchers(client) -> list:
    log.info("Listing network watchers")
    return list(client.network_watchers.list_all())


def _traffic_analytics(flow_log):
    configuration = getattr(flow_log, "flow_analytics_configuration", None)
    return getattr(configuration, "network_watcher_flow_analytics_configuration", None)


def _build_row(flow_log, watcher_name: str) -> dict[str, Any]:
    target_id = utils.s(getattr(flow_log, "target_resource_id", None))
    target_type = _resource_type_from_id(target_id)
    retention = getattr(flow_log, "retention_policy", None)
    fmt = getattr(flow_log, "format", None)
    analytics = _traffic_analytics(flow_log)
    workspace = utils.s(getattr(analytics, "workspace_resource_id", None))
    return {
        "Name": utils.s(getattr(flow_log, "name", None)),
        "Resource Group": utils.extract_resource_group(getattr(flow_log, "id", None)),
        "Network Watcher": watcher_name,
        "Location": utils.s(getattr(flow_log, "location", None)),
        "Flow Log Type": flow_log_type(target_type),
        "Target Resource ID": target_id,
        "Target Type": target_type,
        "Target Name": target_id.rstrip("/").split("/")[-1] if target_id else "",
        "Enabled": "Yes" if getattr(flow_log, "enabled", False) else "No",
        "Storage Account ID": utils.s(getattr(flow_log, "storage_id", None)),
        "Retention Days": utils.s(getattr(retention, "days", None)),
        "Retention Enabled": "Yes" if getattr(retention, "enabled", False) else "No",
        "Format": utils.s(getattr(fmt, "type", None)),
        "Format Version": utils.s(getattr(fmt, "version", None)),
        "Traffic Analytics Enabled": "Yes" if getattr(analytics, "enabled", False) else "No",
        "Traffic Analytics Workspace": workspace.split("/")[-1] if workspace else "",
        "Traffic Analytics Workspace Region": utils.s(getattr(analytics, "workspace_region", None)),
        "Traffic Analytics Interval (min)": utils.s(getattr(analytics, "traffic_analytics_interval", None)),
        "Provisioning State": utils.s(getattr(flow_log, "provisioning_state", None)),
    }


def collect_flow_logs(client, watchers: list, errors: list) -> list[dict[str, Any]]:
    rows = []
    for watcher in watchers:
        watcher_id = utils.s(getattr(watcher, "id", None))
        watcher_name = utils.s(getattr(watcher, "name", None))
        resource_group = utils.extract_resource_group(watcher_id)
        try:
            flow_logs = list(client.flow_logs.list(resource_group, watcher_name))
        except HttpResponseError as e:
            errors.append(utils.error_record(watcher_id or watcher_name, "flow_logs.list", e))
            log.warning("Failed to list flow logs for watcher %s: %s", watcher_name, e)
            continue
        rows.extend(_build_row(flow_log, watcher_name) for flow_log in flow_logs)
    return rows


def _covering_target(resource_id: str, targets: dict[str, tuple[str, str]]) -> tuple[str, str]:
    """Return (flow log name, target id) for a flow log on the resource itself or on one of its subnets."""
    lowered = resource_id.lower()
    if lowered in targets:
        return targets[lowered]
    prefix = f"{lowered}/subnets/"
    for target, covering in targets.items():
        if target.startswith(prefix):
            return covering
    return "", ""


def build_coverage_rows(client, flow_log_rows: list[dict[str, Any]], errors: list) -> list[dict[str, Any]]:
    targets = {
        row["Target Resource ID"].lower(): (row["Name"], row["Target Resource ID"])
        for row in flow_log_rows
        if row["Target Resource ID"] and row["Enabled"] == "Yes"
    }

    rows = []
    for label, operation, listing in (
        ("Network Security Group", "network_security_groups.list_all", client.network_security_groups.list_all),
        ("Virtual Network", "virtual_networks.list_all", client.virtual_networks.list_all),
    ):
        try:
            resources = list(listing())
        except HttpResponseError as e:
            errors.append(utils.error_record(label, operation, e))
            log.warning("Failed to list %s for the coverage sheet: %s", label, e)
            continue
        for resource in resources:
            resource_id = utils.s(getattr(resource, "id", None))
            flow_log_name, target = _covering_target(resource_id, targets)
            rows.append({
                "Resource Type": label,
                "Name": utils.s(getattr(resource, "name", None)),
                "Resource Group": utils.extract_resource_group(resource_id),
                "Flow Log": flow_log_name or "None",
                "Flow Log Target": target,
            })
    return rows


def main(subscription_id: str, subscription_name: str) -> utils.ExportResult:
    environment = utils.detect_environment()
    if not utils.is_service_available_in_environment("network", environment):
        sys.exit(0)

    client = utils.get_azure_client("network", subscription_id)
    watchers = collect_watchers(client)
    if not watchers:
        raise utils.NoResourcesFound("network watchers")

    errors: list = []
    flow_log_rows = collect_flow_logs(client, watchers, errors)
    coverage_rows = build_coverage_rows(client, flow_log_rows, errors)

    sheets = {
        "Flow Logs": pd.DataFrame(flow_log_rows, columns=FLOW_LOG_COLUMNS),
        "Coverage": pd.DataFrame(coverage_rows, columns=COVERAGE_COLUMNS),
    }
    filename = utils.create_export_filename(subscription_name, "flow-logs", "all")
    utils.save_multiple_dataframes_to_excel(sheets, filename, errors=errors)

    uncovered = sum(1 for row in coverage_rows if row["Flow Log"] == "None")
    print(
        f"Exported {len(flow_log_rows)} flow log(s) across {len(watchers)} watcher(s); "
        f"{uncovered} NSG/VNet without one → {filename}"
    )
    log.info(
        "Export complete: %d flow logs, %d watchers, %d uncovered NSG/VNet",
        len(flow_log_rows), len(watchers), uncovered,
    )
    return utils.ExportResult(rows=len(flow_log_rows), filename=filename, errors=errors)


if __name__ == "__main__":
    import runner

    runner.run_exporter(main, "flow-logs")
