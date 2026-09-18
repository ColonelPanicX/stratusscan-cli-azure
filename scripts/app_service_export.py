#!/usr/bin/env python3
"""StratusScanCLI-Azure — App Service / Web Apps Export

web_apps.list does not return siteConfig, so the runtime / TLS / FTPS columns are
blank by default. STRATUSSCAN_APPSERVICE_CONFIG=1 adds one
web_apps.get_configuration call per app to fill them (N+1 against the ARM
request budget; an app whose configuration read fails is recorded, PARTIAL).
"""

import os
import sys
from pathlib import Path

try:
    import utils
except ImportError:
    sys.path.append(str(Path(__file__).parent.parent))
    import utils

import pandas as pd
from azure.core.exceptions import HttpResponseError

log = utils.get_logger()

CONFIG_ENV = "STRATUSSCAN_APPSERVICE_CONFIG"


def config_lookup_enabled() -> bool:
    return os.environ.get(CONFIG_ENV, "").strip() == "1"


def collect_web_apps(client) -> list:
    log.info("Listing all web apps in subscription")
    all_sites = list(client.web_apps.list())
    return [s for s in all_sites if not (s.kind and "functionapp" in s.kind.lower())]


def fetch_site_config(client, app, errors: list):
    rg = app.resource_group or utils.extract_resource_group(app.id)
    try:
        return client.web_apps.get_configuration(rg, app.name)
    except HttpResponseError as exc:
        errors.append(utils.error_record(utils.s(app.name), "web_apps.get_configuration", exc))
        log.warning("Could not read site configuration for %s: %s", app.name, exc)
        return None


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


def _build_row(app, site_config=None) -> dict:
    tags = app.tags or {}
    config = site_config_columns(site_config if site_config is not None else app.site_config)
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


def build_rows(client, apps: list, errors: list) -> list:
    if not config_lookup_enabled():
        return [_build_row(app) for app in apps]
    log.info("%s=1: reading site configuration for %d web app(s)", CONFIG_ENV, len(apps))
    return [_build_row(app, fetch_site_config(client, app, errors)) for app in apps]


def main(subscription_id: str, subscription_name: str) -> utils.ExportResult:
    environment = utils.detect_environment()
    if not utils.is_service_available_in_environment("web", environment):
        sys.exit(0)

    client = utils.get_azure_client("web", subscription_id)
    apps = collect_web_apps(client)
    if not apps:
        raise utils.NoResourcesFound("App Service web apps")

    errors: list = []
    rows = build_rows(client, apps, errors)

    df = pd.DataFrame(rows)
    filename = utils.create_export_filename(subscription_name, "app-service", "all")
    utils.save_dataframe_to_excel(df, filename, sheet_name="App Service", errors=errors)
    print(f"Exported {len(rows)} web app(s) → {filename}")
    log.info("Export complete: %d web apps", len(rows))
    return utils.ExportResult(rows=len(rows), filename=filename, errors=errors)


if __name__ == "__main__":
    import runner

    runner.run_exporter(main, "app-service")
