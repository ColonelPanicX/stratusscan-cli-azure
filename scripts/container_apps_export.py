#!/usr/bin/env python3
"""StratusScanCLI-Azure — Container Apps Export"""

import sys
from pathlib import Path

try:
    import utils
except ImportError:
    sys.path.append(str(Path(__file__).parent.parent))
    import utils

import pandas as pd

utils.setup_logging("container-apps-export")
utils.log_script_start("container_apps_export.py", "Container Apps Export")

log = utils.get_logger()


def collect_apps(subscription_id: str) -> list:
    client = utils.get_azure_client("appcontainers", subscription_id)
    log.info("Listing container apps in subscription %s", subscription_id)
    return list(client.container_apps.list_by_subscription())


def _container_images(app) -> str:
    try:
        containers = app.template.containers or []
        return ", ".join(c.image for c in containers if getattr(c, "image", None))
    except Exception:
        return ""


def main(subscription_id: str, subscription_name: str) -> None:
    environment = utils.detect_environment()
    if not utils.is_service_available_in_environment("appcontainers", environment):
        sys.exit(0)

    apps = collect_apps(subscription_id)
    if not apps:
        print("No container apps found.")
        return

    rows = []
    for app in apps:
        cfg = app.configuration
        ingress = getattr(cfg, "ingress", None) if cfg else None
        tags = app.tags or {}
        rows.append({
            "Name": app.name,
            "Resource Group": utils.extract_resource_group(app.id),
            "Location": app.location,
            "Managed Environment": (app.managed_environment_id or "").split("/")[-1],
            "Provisioning State": str(app.provisioning_state) if app.provisioning_state else "",
            "Latest Revision": app.latest_revision_name or "",
            "Ingress FQDN": getattr(ingress, "fqdn", "") if ingress else "",
            "External Ingress": ("Yes" if getattr(ingress, "external", False) else "No") if ingress else "N/A",
            "Target Port": getattr(ingress, "target_port", "") if ingress else "",
            "Active Revisions Mode": str(getattr(cfg, "active_revisions_mode", "")) if cfg else "",
            "Container Images": _container_images(app),
            "Tags": "; ".join(f"{k}={v}" for k, v in tags.items()),
        })

    df = pd.DataFrame(rows)
    filename = utils.create_export_filename(subscription_name, "container-apps", "all")
    utils.save_dataframe_to_excel(df, filename, sheet_name="Container Apps")
    print(f"Exported {len(rows)} container app(s) → {filename}")
    log.info("Export complete: %d container apps", len(rows))


if __name__ == "__main__":
    sub_id, sub_name = utils.resolve_target_subscription()
    if not sub_id:
        print("ERROR: No subscription configured. Run configure.py first.")
        sys.exit(1)
    main(sub_id, sub_name)
