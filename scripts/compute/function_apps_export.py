#!/usr/bin/env python3
"""StratusScanCLI-Azure — Function Apps Export"""

import sys
from pathlib import Path

try:
    import utils
except ImportError:
    sys.path.append(str(Path(__file__).parent.parent.parent))
    import utils

import pandas as pd

utils.setup_logging("function-apps-export")
utils.log_script_start("function_apps_export.py", "Azure Function Apps Export")

log = utils.get_logger()


def collect_function_apps(subscription_id: str) -> list:
    client = utils.get_azure_client("web", subscription_id)
    log.info("Listing all function apps in subscription %s", subscription_id)
    all_sites = list(client.web_apps.list())
    return [s for s in all_sites if s.kind and "functionapp" in s.kind.lower()]


def main(subscription_id: str, subscription_name: str) -> None:
    environment = utils.detect_environment()
    if not utils.is_service_available_in_environment("web", environment):
        sys.exit(0)

    apps = collect_function_apps(subscription_id)
    if not apps:
        print("No function apps found.")
        return

    rows = []
    for app in apps:
        rg = app.resource_group or (
            utils.extract_resource_group(app.id)
        )
        tags = app.tags or {}
        rows.append({
            "Name": app.name,
            "Resource Group": rg,
            "Location": app.location,
            "Kind": app.kind or "",
            "State": app.state or "",
            "HTTPS Only": app.https_only,
            "Default Hostname": app.default_host_name or "",
            "App Service Plan": (
                app.server_farm_id.split("/")[-1]
                if app.server_farm_id else ""
            ),
            "Runtime Stack": (
                app.site_config.linux_fx_version
                if app.site_config and app.site_config.linux_fx_version
                else ""
            ),
            "Tags": "; ".join(f"{k}={v}" for k, v in tags.items()),
        })

    df = pd.DataFrame(rows)
    filename = utils.create_export_filename(subscription_name, "function-apps", "all")
    utils.save_dataframe_to_excel(df, filename, sheet_name="Function Apps")
    print(f"Exported {len(rows)} function app(s) → {filename}")
    log.info("Export complete: %d function apps", len(rows))


if __name__ == "__main__":
    cfg = utils.get_config()
    sub_id = cfg.get("default_subscription_id", "")
    sub_name = utils.get_subscription_name(sub_id)
    if not sub_id:
        print("ERROR: No subscription configured. Run configure.py first.")
        sys.exit(1)
    main(sub_id, sub_name)
