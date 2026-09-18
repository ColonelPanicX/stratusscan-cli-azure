#!/usr/bin/env python3
"""StratusScanCLI-Azure — Redis Cache Export"""

import sys
from pathlib import Path

try:
    import utils
except ImportError:
    sys.path.append(str(Path(__file__).parent.parent))
    import utils

import pandas as pd

log = utils.get_logger()


def collect_caches(subscription_id: str) -> list:
    client = utils.get_azure_client("redis", subscription_id)
    log.info("Listing Redis caches in subscription %s", subscription_id)
    return list(utils.list_subscription_wide(client.redis, "list_by_subscription", "list"))


def main(subscription_id: str, subscription_name: str) -> utils.ExportResult:
    environment = utils.detect_environment()
    if not utils.is_service_available_in_environment("redis", environment):
        sys.exit(0)

    caches = collect_caches(subscription_id)
    if not caches:
        raise utils.NoResourcesFound("Redis caches")

    errors: list = []
    rows = []
    for cache in caches:
        sku = cache.sku
        tags = cache.tags or {}
        rows.append({
            "Name": cache.name,
            "Resource Group": utils.extract_resource_group(cache.id),
            "Location": cache.location,
            "SKU": sku.name if sku else "",
            "Family": sku.family if sku else "",
            "Capacity": sku.capacity if sku else "",
            "Redis Version": cache.redis_version or "",
            "Provisioning State": cache.provisioning_state or "",
            "Host Name": cache.host_name or "",
            "SSL Port": cache.ssl_port or "",
            "Non-SSL Port": cache.port if cache.enable_non_ssl_port else "Disabled",
            "Minimum TLS Version": utils.s(cache.minimum_tls_version),
            "Public Network Access": cache.public_network_access or "",
            "Shard Count": cache.shard_count if cache.shard_count else "",
            "Tags": "; ".join(f"{k}={v}" for k, v in tags.items()),
        })

    df = pd.DataFrame(rows)
    filename = utils.create_export_filename(subscription_name, "redis-cache", "all")
    utils.save_dataframe_to_excel(df, filename, sheet_name="Redis Cache", errors=errors)
    print(f"Exported {len(rows)} Redis cache(s) → {filename}")
    log.info("Export complete: %d caches", len(rows))
    return utils.ExportResult(rows=len(rows), filename=filename, errors=errors)


if __name__ == "__main__":
    import runner

    runner.run_exporter(main, "redis-cache")
