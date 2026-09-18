#!/usr/bin/env python3
"""StratusScanCLI-Azure — App Service Plans Export

One subscription-wide listing (web.app_service_plans.list()). The plan is the
billing and SLA boundary behind every web app and Function App, so it carries
two findings the app-level exports cannot:

  - Free/Shared tier: neither carries a financially backed SLA
    (https://learn.microsoft.com/azure/app-service/overview-manage-costs#nonproduction-workloads).
  - A plan with zero sites still reserves and bills its VM instances
    (https://learn.microsoft.com/azure/app-service/app-service-plan-manage#delete-an-app-service-plan).

Worker Count is numberOfWorkers — the instances actually allocated — while SKU
Capacity is the configured sku.capacity; the two differ during a scale
operation, so both are exported.
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

log = utils.get_logger()

NO_SLA_TIERS = ("free", "shared")

COLUMNS = [
    "Name", "Resource Group", "Location", "Kind", "SKU Name", "SKU Tier",
    "SKU Size", "SKU Family", "SKU Capacity", "Worker Count",
    "Maximum Worker Count", "Maximum Elastic Worker Count", "Elastic Scale",
    "Linux (Reserved)", "Hyper-V", "Zone Redundant", "Per-Site Scaling",
    "Number of Sites", "Empty Plan", "Free/Shared Tier (no SLA)", "Spot",
    "App Service Environment", "Status", "Provisioning State", "Tags",
]


def collect_plans(subscription_id: str) -> list:
    client = utils.get_azure_client("web", subscription_id)
    log.info("Listing App Service plans in subscription %s", subscription_id)
    return list(client.app_service_plans.list())


def _yes_no(value: Any) -> str:
    if value is None:
        return ""
    return "Yes" if value else "No"


def is_no_sla_tier(tier: str) -> bool:
    return tier.strip().lower() in NO_SLA_TIERS


def build_row(plan) -> dict[str, Any]:
    sku = getattr(plan, "sku", None)
    tier = utils.s(getattr(sku, "tier", None))
    site_count = getattr(plan, "number_of_sites", None)
    hosting_environment = getattr(plan, "hosting_environment_profile", None)
    tags = getattr(plan, "tags", None) or {}

    return {
        "Name": utils.s(getattr(plan, "name", None)),
        "Resource Group": utils.extract_resource_group(getattr(plan, "id", None)),
        "Location": utils.s(getattr(plan, "location", None)),
        "Kind": utils.s(getattr(plan, "kind", None)),
        "SKU Name": utils.s(getattr(sku, "name", None)),
        "SKU Tier": tier,
        "SKU Size": utils.s(getattr(sku, "size", None)),
        "SKU Family": utils.s(getattr(sku, "family", None)),
        "SKU Capacity": utils.s(getattr(sku, "capacity", None)),
        "Worker Count": utils.s(getattr(plan, "number_of_workers", None)),
        "Maximum Worker Count": utils.s(getattr(plan, "maximum_number_of_workers", None)),
        "Maximum Elastic Worker Count": utils.s(
            getattr(plan, "maximum_elastic_worker_count", None)
        ),
        "Elastic Scale": _yes_no(getattr(plan, "elastic_scale_enabled", None)),
        "Linux (Reserved)": _yes_no(getattr(plan, "reserved", None)),
        "Hyper-V": _yes_no(getattr(plan, "hyper_v", None)),
        "Zone Redundant": _yes_no(getattr(plan, "zone_redundant", None)),
        "Per-Site Scaling": _yes_no(getattr(plan, "per_site_scaling", None)),
        "Number of Sites": utils.s(site_count),
        "Empty Plan": _yes_no(site_count == 0) if site_count is not None else "",
        "Free/Shared Tier (no SLA)": _yes_no(is_no_sla_tier(tier)) if tier else "",
        "Spot": _yes_no(getattr(plan, "is_spot", None)),
        "App Service Environment": utils.s(getattr(hosting_environment, "name", None)),
        "Status": utils.s(getattr(plan, "status", None)),
        "Provisioning State": utils.s(getattr(plan, "provisioning_state", None)),
        "Tags": "; ".join(f"{k}={v}" for k, v in tags.items()),
    }


def main(subscription_id: str, subscription_name: str) -> utils.ExportResult:
    environment = utils.detect_environment()
    if not utils.is_service_available_in_environment("web", environment):
        sys.exit(0)

    plans = collect_plans(subscription_id)
    if not plans:
        raise utils.NoResourcesFound("App Service plans")

    rows = [build_row(plan) for plan in plans]
    df = pd.DataFrame(rows, columns=COLUMNS)
    filename = utils.create_export_filename(subscription_name, "app-service-plans", "all")
    utils.save_dataframe_to_excel(df, filename, sheet_name="App Service Plans")

    empty = sum(1 for row in rows if row["Empty Plan"] == "Yes")
    no_sla = sum(1 for row in rows if row["Free/Shared Tier (no SLA)"] == "Yes")
    print(
        f"Exported {len(rows)} App Service plan(s); {empty} with no sites, "
        f"{no_sla} on a tier with no SLA → {filename}"
    )
    log.info(
        "Export complete: %d plans, %d empty, %d without an SLA", len(rows), empty, no_sla
    )
    return utils.ExportResult(rows=len(rows), filename=filename, errors=[])


if __name__ == "__main__":
    import runner

    runner.run_exporter(main, "app-service-plans")
