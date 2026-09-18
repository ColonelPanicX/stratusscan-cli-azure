#!/usr/bin/env python3
"""StratusScanCLI-Azure — Container Instances (ACI) Export"""

import sys
from pathlib import Path

try:
    import utils
except ImportError:
    sys.path.append(str(Path(__file__).parent.parent))
    import utils

import pandas as pd

log = utils.get_logger()


def collect_groups(subscription_id: str) -> list:
    client = utils.get_azure_client("containerinstance", subscription_id)
    log.info("Listing container groups in subscription %s", subscription_id)
    return list(client.container_groups.list())


def _images(group) -> str:
    try:
        return ", ".join(c.image for c in (group.containers or []) if getattr(c, "image", None))
    except Exception:
        return ""


def _total_resources(group) -> str:
    try:
        cpu = 0.0
        mem = 0.0
        for c in group.containers or []:
            req = c.resources.requests
            cpu += req.cpu or 0
            mem += req.memory_in_gb or 0
        return f"{cpu} vCPU / {mem} GB"
    except Exception:
        return ""


def main(subscription_id: str, subscription_name: str) -> utils.ExportResult:
    environment = utils.detect_environment()
    if not utils.is_service_available_in_environment("containerinstance", environment):
        sys.exit(0)

    groups = collect_groups(subscription_id)
    if not groups:
        raise utils.NoResourcesFound("container groups")

    rows = []
    for group in groups:
        ip = group.ip_address
        tags = group.tags or {}
        rows.append({
            "Name": group.name,
            "Resource Group": utils.extract_resource_group(group.id),
            "Location": group.location,
            "OS Type": utils.s(group.os_type),
            "Restart Policy": utils.s(group.restart_policy),
            "Provisioning State": utils.s(group.provisioning_state),
            "IP Address": getattr(ip, "ip", "") if ip else "",
            "IP Type": utils.s(getattr(ip, "type", None)) if ip else "",
            "FQDN": getattr(ip, "fqdn", "") if ip else "",
            "Container Count": len(group.containers or []),
            "Images": _images(group),
            "Total Requested": _total_resources(group),
            "Tags": "; ".join(f"{k}={v}" for k, v in tags.items()),
        })

    df = pd.DataFrame(rows)
    filename = utils.create_export_filename(subscription_name, "container-instances", "all")
    utils.save_dataframe_to_excel(df, filename, sheet_name="Container Instances")
    print(f"Exported {len(rows)} container group(s) → {filename}")
    log.info("Export complete: %d container groups", len(rows))
    return utils.ExportResult(rows=len(rows), filename=filename, errors=[])


if __name__ == "__main__":
    import runner

    runner.run_exporter(main, "container-instances")
