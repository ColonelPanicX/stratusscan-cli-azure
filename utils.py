#!/usr/bin/env python3
"""
StratusScanCLI-Azure — Shared Utilities Module
Version: v0.1.0

Shared utility functions for all AzureScan exporter scripts.
Handles credential management, client factory, environment detection,
logging, Excel output, and config I/O.

Design constraints:
- No print() calls in this module — return structured results only
- setup_logging() must be called explicitly by each script; never auto-called on import
- CloudShell-first: all paths must work in a fresh Azure Cloud Shell session
"""

import datetime
import json
import logging
import os
import platform
import sys
import threading
import warnings
from importlib.metadata import version as _pkg_version, PackageNotFoundError
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

# ---------------------------------------------------------------------------
# Version
# ---------------------------------------------------------------------------

def get_version() -> str:
    try:
        return _pkg_version("stratusscan-cli-azure")
    except PackageNotFoundError:
        return "dev"


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logger: Optional[logging.Logger] = None
_logging_configured = False


def _cleanup_old_logs(logs_dir: Path, retention_days: int = 14) -> None:
    try:
        cutoff = (datetime.datetime.now() - datetime.timedelta(days=retention_days)).timestamp()
        for f in logs_dir.glob("*.log"):
            try:
                if f.stat().st_mtime < cutoff:
                    f.unlink()
            except Exception:
                pass
    except Exception:
        pass


def setup_logging(script_name: str = "azurescan", log_to_file: bool = True) -> logging.Logger:
    global logger, _logging_configured

    logger = logging.getLogger("azurescan")
    logger.setLevel(logging.DEBUG)
    logger.handlers = []

    console_fmt = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
    file_fmt = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(funcName)s:%(lineno)d - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.WARNING)
    console_handler.setFormatter(console_fmt)
    logger.addHandler(console_handler)

    if log_to_file:
        try:
            logs_dir = Path(__file__).parent / "logs"
            logs_dir.mkdir(exist_ok=True)
            _cleanup_old_logs(logs_dir)
            timestamp = datetime.datetime.now().strftime("%m.%d.%Y-%H%M")
            log_path = logs_dir / f"logs-{script_name}-{timestamp}.log"
            fh = logging.FileHandler(log_path, mode="w", encoding="utf-8")
            fh.setLevel(logging.DEBUG)
            fh.setFormatter(file_fmt)
            logger.addHandler(fh)
            logger.info("AzureScan logging initialized — %s", log_path)
        except Exception as exc:
            logger.warning("File logging unavailable: %s", exc)

    for noisy_logger in ("azure", "msrest", "urllib3"):
        logging.getLogger(noisy_logger).setLevel(logging.ERROR)

    _logging_configured = True
    return logger


def get_logger() -> logging.Logger:
    global logger, _logging_configured
    if logger is None:
        nl = logging.getLogger("azurescan")
        if not nl.handlers:
            nl.addHandler(logging.NullHandler())
        return nl
    return logger


def log_script_start(script_name: str, description: str = "") -> None:
    log = get_logger()
    log.info("=" * 80)
    log.info("Script: %s  |  %s", script_name, description)
    log.info("Version: %s", get_version())
    log.info("Started: %s", datetime.datetime.now().isoformat())
    log.info("=" * 80)


def log_system_info() -> None:
    log = get_logger()
    log.info("Platform: %s %s", platform.system(), platform.release())
    log.info("Python: %s", sys.version.split()[0])


# ---------------------------------------------------------------------------
# CI / automation mode
# ---------------------------------------------------------------------------

def is_auto_run() -> bool:
    return os.environ.get("AZURESCAN_AUTO_RUN", "").strip() == "1"


def get_auto_subscriptions() -> List[str]:
    raw = os.environ.get("AZURESCAN_SUBSCRIPTIONS", "").strip()
    if not raw:
        return []
    return [s.strip() for s in raw.split(",") if s.strip()]


# ---------------------------------------------------------------------------
# Timestamp & filename helpers
# ---------------------------------------------------------------------------

def get_current_timestamp() -> str:
    """Return today's date as MM.DD.YYYY."""
    return datetime.datetime.now().strftime("%m.%d.%Y")


def _sanitize_name(name: str) -> str:
    """Replace characters that are unsafe in filenames with hyphens."""
    import re
    return re.sub(r"[^\w\-]", "-", name).strip("-")


def create_export_filename(subscription_name: str, resource_type: str, suffix: str) -> str:
    """
    Return a full path to the output file.

    Format: output/{SUBSCRIPTION-NAME}-{resource-type}-{suffix}-export-{MM.DD.YYYY}.xlsx
    """
    out_dir = Path(__file__).parent / "output"
    out_dir.mkdir(exist_ok=True)
    safe_sub = _sanitize_name(subscription_name).upper()
    date_str = get_current_timestamp()
    filename = f"{safe_sub}-{resource_type}-{suffix}-export-{date_str}.xlsx"
    return str(out_dir / filename)


def extract_resource_group(resource_id: Optional[str]) -> str:
    """
    Return the resource group name from an Azure resource ID, or "" if absent.

    Azure APIs are inconsistent about the resourceGroups segment casing, so
    callers should use this instead of a literal split on "/resourceGroups/".
    """
    if not resource_id:
        return ""
    parts = resource_id.split("/")
    for i, part in enumerate(parts):
        if part.lower() == "resourcegroups" and i + 1 < len(parts):
            return parts[i + 1]
    return ""


def archive_outputs() -> Optional[str]:
    """
    Bundle every .xlsx in output/ into a single dated zip.

    Returns the zip path, or None if there are no exports to archive.
    """
    import zipfile

    out_dir = Path(__file__).parent / "output"
    exports = sorted(out_dir.glob("*.xlsx"))
    if not exports:
        return None

    zip_path = out_dir / f"exports-{get_current_timestamp()}.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for export in exports:
            zf.write(export, arcname=export.name)
    return str(zip_path)


# ---------------------------------------------------------------------------
# Excel output
# ---------------------------------------------------------------------------

def _adjust_column_widths(ws) -> None:
    """Auto-fit column widths in an openpyxl worksheet."""
    try:
        from openpyxl.utils import get_column_letter
        for col_idx, col_cells in enumerate(ws.columns, 1):
            max_len = 0
            for cell in col_cells:
                try:
                    cell_len = len(str(cell.value)) if cell.value is not None else 0
                    max_len = max(max_len, cell_len)
                except Exception:
                    pass
            ws.column_dimensions[get_column_letter(col_idx)].width = min(max_len + 4, 60)
    except Exception:
        pass


def save_dataframe_to_excel(df, filename: str, sheet_name: str = "Export") -> str:
    """
    Write a single DataFrame to an Excel workbook.

    Returns the filename on success, raises on failure.
    """
    import pandas as pd
    from openpyxl import load_workbook

    log = get_logger()
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            df.to_excel(filename, index=False, sheet_name=sheet_name, engine="openpyxl")
        wb = load_workbook(filename)
        ws = wb[sheet_name]
        _adjust_column_widths(ws)
        wb.save(filename)
        log.info("Saved %d rows → %s", len(df), filename)
        return filename
    except Exception as exc:
        log.error("Failed to save %s: %s", filename, exc)
        raise


def save_multiple_dataframes_to_excel(sheets: Dict[str, Any], filename: str) -> str:
    """
    Write multiple DataFrames to an Excel workbook, one sheet per key.

    Args:
        sheets: {sheet_name: DataFrame}
        filename: target file path

    Returns the filename on success.
    """
    import pandas as pd
    from openpyxl import load_workbook

    log = get_logger()
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            with pd.ExcelWriter(filename, engine="openpyxl") as writer:
                for sheet_name, df in sheets.items():
                    safe_name = sheet_name[:31]  # Excel sheet name limit
                    df.to_excel(writer, index=False, sheet_name=safe_name)
        wb = load_workbook(filename)
        for ws in wb.worksheets:
            _adjust_column_widths(ws)
        wb.save(filename)
        log.info("Saved %d sheet(s) → %s", len(sheets), filename)
        return filename
    except Exception as exc:
        log.error("Failed to save %s: %s", filename, exc)
        raise


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

_config_lock = threading.Lock()
_config_cache: Optional[Dict] = None

_DEFAULT_CONFIG: Dict = {
    "subscriptions": [],
    "default_subscription_id": "",
    "environment": "public",
    "output_dir": "output",
    "log_retention_days": 14,
}


def get_config() -> Dict:
    """Thread-safe singleton loader for config.json."""
    global _config_cache
    with _config_lock:
        if _config_cache is not None:
            return _config_cache
        config_path = Path(__file__).parent / "config.json"
        if config_path.exists():
            try:
                with open(config_path, encoding="utf-8") as fh:
                    loaded = json.load(fh)
                _config_cache = {**_DEFAULT_CONFIG, **loaded}
            except Exception as exc:
                get_logger().warning("Could not load config.json: %s — using defaults", exc)
                _config_cache = dict(_DEFAULT_CONFIG)
        else:
            _config_cache = dict(_DEFAULT_CONFIG)
        return _config_cache


def save_config(data: Dict) -> None:
    global _config_cache
    config_path = Path(__file__).parent / "config.json"
    with _config_lock:
        with open(config_path, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2)
        _config_cache = data


# ---------------------------------------------------------------------------
# Azure environment detection
# ---------------------------------------------------------------------------

# Services unavailable in AzureUSGovernment (extend as needed)
_GOV_UNAVAILABLE: List[str] = []


def detect_environment() -> str:
    """
    Return 'government' if running in AzureUSGovernment, otherwise 'public'.

    Detection order:
    1. AZURE_ENVIRONMENT env var ('AzureUSGovernment' → 'government')
    2. config.json 'environment' key
    3. Default: 'public'
    """
    env_var = os.environ.get("AZURE_ENVIRONMENT", "").strip().lower()
    if env_var in ("azureusgovernment", "government", "usgov"):
        return "government"
    if env_var in ("azurepubliccloud", "public", "azurecloud"):
        return "public"
    cfg = get_config()
    if cfg.get("environment", "public").lower() in ("government", "azureusgovernment"):
        return "government"
    return "public"


def is_service_available_in_environment(service: str, environment: str) -> bool:
    """
    Return False if the given service is unavailable in the given environment.

    Args:
        service: lowercase service key (e.g. 'cosmosdb', 'web')
        environment: 'public' or 'government'
    """
    if environment == "government" and service.lower() in _GOV_UNAVAILABLE:
        get_logger().warning("Service '%s' is not available in AzureUSGovernment — skipping.", service)
        return False
    return True


# ---------------------------------------------------------------------------
# Credential & client factory
# ---------------------------------------------------------------------------

_credential_lock = threading.Lock()
_credential_cache: Optional[Any] = None


class _GovernmentCredential:
    """Rewrite public ARM token scopes to the Azure Government ARM scope."""

    def __init__(self, credential: Any) -> None:
        self._credential = credential

    def get_token(self, *scopes: str, **kwargs: Any) -> Any:
        gov_scopes = tuple(
            f"{_GOV_BASE_URL}/.default"
            if scope in ("https://management.azure.com/.default", "https://management.azure.com")
            else scope
            for scope in scopes
        )
        return self._credential.get_token(*gov_scopes, **kwargs)


def _get_credential():
    """Return a cached DefaultAzureCredential, configured for the active environment."""
    global _credential_cache
    with _credential_lock:
        if _credential_cache is not None:
            return _credential_cache
        try:
            from azure.identity import DefaultAzureCredential, AzureAuthorityHosts
        except ImportError as exc:
            raise ImportError("azure-identity is required: pip install azure-identity") from exc

        environment = detect_environment()
        if environment == "government":
            _credential_cache = _GovernmentCredential(
                DefaultAzureCredential(authority=AzureAuthorityHosts.AZURE_GOVERNMENT)
            )
        else:
            _credential_cache = DefaultAzureCredential()
        return _credential_cache


# Lazy import map: service_name → (module_path, class_name, needs_subscription_id)
_CLIENT_MAP: Dict[str, tuple] = {
    "subscription": ("azure.mgmt.resource.subscriptions", "SubscriptionClient", False),
    "resource": ("azure.mgmt.resource.resources", "ResourceManagementClient", True),
    "compute": ("azure.mgmt.compute", "ComputeManagementClient", True),
    "network": ("azure.mgmt.network", "NetworkManagementClient", True),
    "storage": ("azure.mgmt.storage", "StorageManagementClient", True),
    "keyvault": ("azure.mgmt.keyvault", "KeyVaultManagementClient", True),
    "authorization": ("azure.mgmt.authorization", "AuthorizationManagementClient", True),
    "containerservice": ("azure.mgmt.containerservice", "ContainerServiceClient", True),
    "web": ("azure.mgmt.web", "WebSiteManagementClient", True),
    "sql": ("azure.mgmt.sql", "SqlManagementClient", True),
    "cosmosdb": ("azure.mgmt.cosmosdb", "CosmosDBManagementClient", True),
    "policy": ("azure.mgmt.resource.policy", "PolicyClient", True),
    "locks": ("azure.mgmt.resource.locks", "ManagementLockClient", True),
    "managementgroups": ("azure.mgmt.managementgroups", "ManagementGroupsAPI", False),
    "security": ("azure.mgmt.security", "SecurityCenter", True),
    "advisor": ("azure.mgmt.advisor", "AdvisorManagementClient", True),
    "monitor": ("azure.mgmt.monitor", "MonitorManagementClient", True),
    "loganalytics": ("azure.mgmt.loganalytics", "LogAnalyticsManagementClient", True),
    "costmanagement": ("azure.mgmt.costmanagement", "CostManagementClient", False),
    "postgresql": ("azure.mgmt.postgresqlflexibleservers", "PostgreSQLManagementClient", True),
    "mysql": ("azure.mgmt.mysqlflexibleservers", "MySQLManagementClient", True),
    "redis": ("azure.mgmt.redis", "RedisManagementClient", True),
    "containerregistry": ("azure.mgmt.containerregistry", "ContainerRegistryManagementClient", True),
    "appcontainers": ("azure.mgmt.appcontainers", "ContainerAppsAPIClient", True),
    "containerinstance": ("azure.mgmt.containerinstance", "ContainerInstanceManagementClient", True),
    "dns": ("azure.mgmt.dns", "DnsManagementClient", True),
    "privatedns": ("azure.mgmt.privatedns", "PrivateDnsManagementClient", True),
    "cdn": ("azure.mgmt.cdn", "CdnManagementClient", True),
    "trafficmanager": ("azure.mgmt.trafficmanager", "TrafficManagerManagementClient", True),
    "eventhub": ("azure.mgmt.eventhub", "EventHubManagementClient", True),
    "servicebus": ("azure.mgmt.servicebus", "ServiceBusManagementClient", True),
    "apimanagement": ("azure.mgmt.apimanagement", "ApiManagementClient", True),
    "logic": ("azure.mgmt.logic", "LogicManagementClient", True),
    "msi": ("azure.mgmt.msi", "ManagedServiceIdentityClient", True),
    "policyinsights": ("azure.mgmt.policyinsights", "PolicyInsightsClient", True),
    "automation": ("azure.mgmt.automation", "AutomationClient", True),
    "batch": ("azure.mgmt.batch", "BatchManagementClient", True),
    "recoveryservices": ("azure.mgmt.recoveryservices", "RecoveryServicesClient", True),
    "applicationinsights": ("azure.mgmt.applicationinsights", "ApplicationInsightsManagementClient", True),
}

# Government cloud base URL override
_GOV_BASE_URL = "https://management.usgovcloudapi.net"

# Azure Government can lag public cloud SDK defaults. Keep overrides targeted
# to services that have been observed failing against the default api-version.
_GOV_API_VERSIONS: Dict[str, str] = {
    "storage": "2025-06-01",
    "web": "2025-03-01",
}


def get_azure_client(service_name: str, subscription_id: Optional[str] = None) -> Any:
    """
    Return an instantiated azure-mgmt-* client for the given service.

    Args:
        service_name: key from _CLIENT_MAP (e.g. 'compute', 'network')
        subscription_id: required for all services except 'subscription'

    Raises:
        ValueError: unknown service name or missing subscription_id
        ImportError: required azure-mgmt-* package not installed
    """
    key = service_name.lower()
    if key not in _CLIENT_MAP:
        raise ValueError(
            f"Unknown service '{service_name}'. Known services: {sorted(_CLIENT_MAP)}"
        )

    module_path, class_name, needs_sub = _CLIENT_MAP[key]
    if needs_sub and not subscription_id:
        raise ValueError(f"subscription_id is required for service '{service_name}'")

    try:
        import importlib
        mod = importlib.import_module(module_path)
        cls = getattr(mod, class_name)
    except ImportError as exc:
        pkg = module_path.replace(".", "-")
        raise ImportError(f"Missing package: pip install {pkg}") from exc

    cred = _get_credential()
    environment = detect_environment()

    kwargs: Dict[str, Any] = {}
    if environment == "government":
        kwargs["base_url"] = _GOV_BASE_URL
        kwargs["credential_scopes"] = [f"{_GOV_BASE_URL}/.default"]
        if key in _GOV_API_VERSIONS:
            kwargs["api_version"] = _GOV_API_VERSIONS[key]

    if needs_sub:
        return cls(cred, subscription_id, **kwargs)
    return cls(cred, **kwargs)


# ---------------------------------------------------------------------------
# Subscription helpers
# ---------------------------------------------------------------------------

def list_subscriptions() -> List[Dict[str, str]]:
    """
    Return all subscriptions accessible to the current credential.

    Returns:
        List of dicts with keys: id, name, state, tenant_id
    """
    client = get_azure_client("subscription")
    subs = []
    try:
        for sub in client.subscriptions.list():
            subs.append({
                "id": sub.subscription_id,
                "name": sub.display_name or sub.subscription_id,
                "state": str(sub.state) if sub.state else "",
                "tenant_id": sub.tenant_id or "",
            })
    except Exception as exc:
        get_logger().error("Failed to list subscriptions: %s", exc)
    return subs


def get_subscription_name(subscription_id: str) -> str:
    """Return the display name for a subscription ID, or the ID itself on failure."""
    cfg = get_config()
    for sub in cfg.get("subscriptions", []):
        if sub.get("id") == subscription_id:
            return sub.get("name", subscription_id)
    return subscription_id


# ---------------------------------------------------------------------------
# Interactive menu (shared by azurescan.py and configure.py)
# ---------------------------------------------------------------------------

def prompt_menu(
    title: str,
    options: List[str],
    allow_back: bool = True,
    allow_exit: bool = True,
) -> Union[int, str]:
    """
    Display a numbered menu and return the user's choice.

    In auto-run mode, returns 1 without prompting.

    Returns:
        int 1..N for a numbered choice,
        'back' if user enters 'b',
        'exit' if user enters 'x'.
    """
    if is_auto_run():
        return 1

    print(f"\n{title}")
    print("=" * 64)
    for i, opt in enumerate(options, 1):
        print(f"  {i}. {opt}")
    print("-" * 64)
    footer = []
    if allow_back:
        footer.append("b. Back")
    if allow_exit:
        footer.append("x. Exit")
    if footer:
        print("  " + "    ".join(footer))
    print("=" * 64)

    valid = {str(i) for i in range(1, len(options) + 1)}
    if allow_back:
        valid.add("b")
    if allow_exit:
        valid.add("x")

    while True:
        try:
            choice = input("Enter your choice: ").strip().lower()
        except KeyboardInterrupt:
            print()
            return "exit" if allow_exit else "back"
        if choice in valid:
            if choice == "b":
                return "back"
            if choice == "x":
                return "exit"
            return int(choice)
        print("Invalid choice. Please try again.")
