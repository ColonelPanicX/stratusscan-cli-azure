#!/usr/bin/env python3
"""StratusScanCLI-Azure — Front Door & CDN Profiles Export"""

import sys
from pathlib import Path

try:
    import utils
except ImportError:
    sys.path.append(str(Path(__file__).parent.parent))
    import utils

import pandas as pd

utils.setup_logging("front-door-export")
utils.log_script_start("front_door_export.py", "Front Door & CDN Profiles Export")

log = utils.get_logger()


def collect_profiles(subscription_id: str) -> list:
    client = utils.get_azure_client("cdn", subscription_id)
    log.info("Listing Front Door / CDN profiles in subscription %s", subscription_id)
    return list(client.profiles.list())


def main(subscription_id: str, subscription_name: str) -> None:
    environment = utils.detect_environment()
    if not utils.is_service_available_in_environment("cdn", environment):
        sys.exit(0)

    profiles = collect_profiles(subscription_id)
    if not profiles:
        print("No Front Door or CDN profiles found.")
        return

    rows = []
    for prof in profiles:
        sku = prof.sku
        tags = prof.tags or {}
        rows.append({
            "Name": prof.name,
            "Resource Group": utils.extract_resource_group(prof.id),
            "Location": prof.location,
            "SKU": sku.name if sku else "",
            "Kind": getattr(prof, "kind", "") or "",
            "Provisioning State": str(prof.provisioning_state) if prof.provisioning_state else "",
            "Resource State": str(prof.resource_state) if prof.resource_state else "",
            "Front Door ID": getattr(prof, "front_door_id", "") or "",
            "Tags": "; ".join(f"{k}={v}" for k, v in tags.items()),
        })

    df = pd.DataFrame(rows)
    filename = utils.create_export_filename(subscription_name, "front-door-cdn", "all")
    utils.save_dataframe_to_excel(df, filename, sheet_name="Front Door & CDN")
    print(f"Exported {len(rows)} Front Door / CDN profile(s) → {filename}")
    log.info("Export complete: %d profiles", len(rows))


if __name__ == "__main__":
    sub_id, sub_name = utils.resolve_target_subscription()
    if not sub_id:
        print("ERROR: No subscription configured. Run configure.py first.")
        sys.exit(1)
    main(sub_id, sub_name)
