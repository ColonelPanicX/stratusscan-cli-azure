#!/usr/bin/env python3
"""StratusScanCLI-Azure — Azure SQL Servers & Databases Export

Two sheets: one row per logical server (including servers with no user
databases) and one row per user database. The server listing expands
administrators/activedirectory so Entra-only authentication is read from the
same call, with no per-server round trip.
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
from azure.core.exceptions import HttpResponseError

log = utils.get_logger()

_SERVERS_EXPAND = "administrators/activedirectory"


def _error_code(exc: BaseException) -> str:
    code = getattr(getattr(exc, "error", None), "code", None)
    if code:
        return utils.s(code)
    status = getattr(exc, "status_code", None)
    if status:
        return f"HTTP {status}"
    return type(exc).__name__


def _yes_no(value: Any) -> str:
    if value is None:
        return ""
    return "Yes" if value else "No"


def _build_server_row(server, rg: str, database_cell: Any) -> dict[str, Any]:
    administrators = getattr(server, "administrators", None)
    return {
        "Server Name": utils.s(server.name),
        "Resource Group": rg,
        "Location": utils.s(server.location),
        "Version": utils.s(getattr(server, "version", None)),
        "State": utils.s(getattr(server, "state", None)),
        "Server FQDN": utils.s(getattr(server, "fully_qualified_domain_name", None)),
        "Public Network Access": utils.s(getattr(server, "public_network_access", None)),
        "Restrict Outbound Network Access": utils.s(getattr(server, "restrict_outbound_network_access", None)),
        "Minimal TLS Version": utils.s(getattr(server, "minimal_tls_version", None)),
        "Entra Admin Login": utils.s(getattr(administrators, "login", None)),
        "Entra-Only Authentication": _yes_no(getattr(administrators, "azure_ad_only_authentication", None)),
        "Databases": database_cell,
    }


def _build_database_row(server, rg: str, db) -> dict[str, Any]:
    sku = getattr(db, "sku", None)
    max_size_bytes = getattr(db, "max_size_bytes", None)
    return {
        "Server Name": utils.s(server.name),
        "Resource Group": rg,
        "Location": utils.s(server.location),
        "Database Name": utils.s(db.name),
        "SKU": utils.s(getattr(sku, "name", None)),
        "Edition": utils.s(getattr(sku, "tier", None)),
        "Max Size (GB)": round(max_size_bytes / (1024 ** 3), 2) if max_size_bytes else "",
        "Status": utils.s(getattr(db, "status", None)),
        "Zone Redundant": getattr(db, "zone_redundant", None),
        "Collation": utils.s(getattr(db, "collation", None)),
        "Server FQDN": utils.s(getattr(server, "fully_qualified_domain_name", None)),
        "TLS Version": utils.s(getattr(server, "minimal_tls_version", None)),
        "Tags": "; ".join(f"{k}={v}" for k, v in (getattr(db, "tags", None) or {}).items()),
        "Backup Storage Redundancy": utils.s(getattr(db, "requested_backup_storage_redundancy", None)),
        "Ledger": _yes_no(getattr(db, "is_ledger_on", None)),
    }


def collect_sql_servers_and_dbs(subscription_id: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list]:
    """Return (server_rows, database_rows, errors). A server whose database listing fails carries the error code in its row and in errors."""
    client = utils.get_azure_client("sql", subscription_id)
    log.info("Listing all SQL servers in subscription %s", subscription_id)
    servers = list(client.servers.list(expand=_SERVERS_EXPAND))

    server_rows: list[dict[str, Any]] = []
    db_rows: list[dict[str, Any]] = []
    errors: list = []
    for server in servers:
        rg = utils.extract_resource_group(server.id)
        try:
            databases = list(client.databases.list_by_server(rg, server.name))
        except HttpResponseError as exc:
            errors.append(utils.error_record(utils.s(server.name), "databases.list_by_server", exc))
            log.warning("Could not list databases for server %s: %s", server.name, exc)
            server_rows.append(_build_server_row(server, rg, f"ERROR ({_error_code(exc)})"))
            continue

        user_databases = [db for db in databases if db.name != "master"]
        server_rows.append(_build_server_row(server, rg, len(user_databases)))
        for db in user_databases:
            db_rows.append(_build_database_row(server, rg, db))
    return server_rows, db_rows, errors


def main(subscription_id: str, subscription_name: str) -> utils.ExportResult:
    environment = utils.detect_environment()
    if not utils.is_service_available_in_environment("sql", environment):
        sys.exit(0)

    server_rows, db_rows, errors = collect_sql_servers_and_dbs(subscription_id)
    if not server_rows:
        raise utils.NoResourcesFound("Azure SQL servers")

    sheets = {"Servers": pd.DataFrame(server_rows)}
    if db_rows:
        sheets["Databases"] = pd.DataFrame(db_rows)

    filename = utils.create_export_filename(subscription_name, "azure-sql", "all")
    utils.save_multiple_dataframes_to_excel(sheets, filename, errors=errors)
    print(f"Exported {len(server_rows)} server(s), {len(db_rows)} database(s) → {filename}")
    log.info("Export complete: %d servers, %d databases", len(server_rows), len(db_rows))
    return utils.ExportResult(rows=len(server_rows) + len(db_rows), filename=filename, errors=errors)


if __name__ == "__main__":
    import runner

    runner.run_exporter(main, "azure-sql")
