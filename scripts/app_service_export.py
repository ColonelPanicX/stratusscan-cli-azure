#!/usr/bin/env python3
"""StratusScanCLI-Azure — App Service / Web Apps Export"""

import sys
from pathlib import Path

try:
    import utils
except ImportError:
    sys.path.append(str(Path(__file__).parent.parent))
    import utils

import pandas as pd

utils.setup_logging("app-service-export")
utils.log_script_start("app_service_export.py", "Azure App Service / Web Apps Export")

log = utils.get_logger()


def collect_web_apps(subscription_id: str) -> list:
    client = utils.get_azure_client("web", subscription_id)
    log.info("Listing all web apps in subscription %s", subscription_id)
    all_sites = list(client.web_apps.list())
    return [s for s in all_sites if not (s.kind and "functionapp" in s.kind.lower())]


def site_config_columns(site_config) -> dict:
    """Runtime columns read from the listed siteConfig; all blank when the list omits it."""
    if site_config is None:
        return {
            "Runtime Stack": "", ".NET Version": "", "Node Version": "", "Python Version": "",
            "PHP Version": "", "Java Version": "", "Min TLS Version": "", "FTPS State": "",
        }
    return {
        "Runtime Stack": site_config.linux_fx_version or site_config.windows_fx_version or "",
        ".NET Version": utils.s(site_config.net_framework_version),
        "Node Version": utils.s(site_config.node_version),
        "Python Version": utils.s(site_config.python_version),
        "PHP Version": utils.s(site_config.php_version),
        "Java Version": utils.s(site_config.java_version),
        "Min TLS Version": utils.s(site_config.min_tls_version),
        "FTPS State": utils.s(site_config.ftps_state),
    }


def _build_row(app) -> dict:
    tags = app.tags or {}
    config = site_config_columns(app.site_config)
    return {
        "Name": app.name,
        "Resource Group": app.resource_group or utils.extract_resource_group(app.id),
        "Location": app.location,
        "Kind": app.kind or "",
        "State": app.state or "",
        "HTTPS Only": "" if app.https_only is None else app.https_only,
        "Default Hostname": app.default_host_name or "",
        "App Service Plan": app.server_farm_id.split("/")[-1] if app.server_farm_id else "",
        "Runtime Stack": config["Runtime Stack"],
        "Outbound IPs": app.outbound_ip_addresses or "",
        "Tags": "; ".join(f"{k}={v}" for k, v in tags.items()),
        ".NET Version": config[".NET Version"],
        "Node Version": config["Node Version"],
        "Python Version": config["Python Version"],
        "PHP Version": config["PHP Version"],
        "Java Version": config["Java Version"],
        "Min TLS Version": config["Min TLS Version"],
        "FTPS State": config["FTPS State"],
        "Public Network Access": utils.s(app.public_network_access),
    }


def main(subscription_id: str, subscription_name: str) -> None:
    environment = utils.detect_environment()
    if not utils.is_service_available_in_environment("web", environment):
        sys.exit(0)

    apps = collect_web_apps(subscription_id)
    if not apps:
        print("No App Service web apps found.")
        return

    rows = [_build_row(app) for app in apps]

    df = pd.DataFrame(rows)
    filename = utils.create_export_filename(subscription_name, "app-service", "all")
    utils.save_dataframe_to_excel(df, filename, sheet_name="App Service")
    print(f"Exported {len(rows)} web app(s) → {filename}")
    log.info("Export complete: %d web apps", len(rows))


if __name__ == "__main__":
    sub_id, sub_name = utils.resolve_target_subscription()
    if not sub_id:
        print("ERROR: No subscription configured. Run configure.py first.")
        sys.exit(1)
    main(sub_id, sub_name)
