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

utils.setup_logging("redis-cache-export")
utils.log_script_start("redis_cache_export.py", "Redis Cache Export")

log = utils.get_logger()


def collect_caches(subscription_id: str) -> list:
    client = utils.get_azure_client("redis", subscription_id)
    log.info("Listing Redis caches in subscription %s", subscription_id)
    if hasattr(client.redis, "list"):
        return list(client.redis.list())

    resource = utils.get_azure_client("resource", subscription_id)
    caches = []
    for rg in resource.resource_groups.list():
        try:
            caches.extend(client.redis.list_by_resource_group(rg.name))
        except Exception as exc:
            log.warning("Failed to list Redis caches in %s: %s", rg.name, exc)
    return caches


def main(subscription_id: str, subscription_name: str) -> None:
    environment = utils.detect_environment()
    if not utils.is_service_available_in_environment("redis", environment):
        sys.exit(0)

    caches = collect_caches(subscription_id)
    if not caches:
        print("No Redis caches found.")
        return

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
            "Minimum TLS Version": str(cache.minimum_tls_version) if cache.minimum_tls_version else "",
            "Public Network Access": cache.public_network_access or "",
            "Shard Count": cache.shard_count if cache.shard_count else "",
            "Tags": "; ".join(f"{k}={v}" for k, v in tags.items()),
        })

    df = pd.DataFrame(rows)
    filename = utils.create_export_filename(subscription_name, "redis-cache", "all")
    utils.save_dataframe_to_excel(df, filename, sheet_name="Redis Cache")
    print(f"Exported {len(rows)} Redis cache(s) → {filename}")
    log.info("Export complete: %d caches", len(rows))


if __name__ == "__main__":
    sub_id, sub_name = utils.resolve_target_subscription()
    if not sub_id:
        print("ERROR: No subscription configured. Run configure.py first.")
        sys.exit(1)
    main(sub_id, sub_name)
