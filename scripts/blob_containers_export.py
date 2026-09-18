#!/usr/bin/env python3
"""StratusScanCLI-Azure — Blob Containers Inventory Export

One blob_containers.list call per storage account. The Storage resource provider
allows 100 list operations per 5 minutes per subscription per region, so a
subscription with many accounts in one region can be throttled mid-run. A 429 is
retried once after the Retry-After the service asks for; a second 429, or a 429
without Retry-After, is recorded for that account (PARTIAL) rather than dropped.
STRATUSSCAN_STORAGE_LIST_PACE_S (seconds, default 0) spaces the per-account calls.
"""

import os
import sys
import time
from functools import partial
from pathlib import Path
from typing import Any, Callable, Optional

try:
    import utils
except ImportError:
    sys.path.append(str(Path(__file__).parent.parent))
    import utils

import pandas as pd
from azure.core.exceptions import HttpResponseError

utils.setup_logging("blob-containers-export")
utils.log_script_start("blob_containers_export.py", "Blob Containers Inventory Export")

log = utils.get_logger()

PACE_ENV = "STRATUSSCAN_STORAGE_LIST_PACE_S"


def list_pace_seconds() -> float:
    raw = os.environ.get(PACE_ENV, "").strip()
    if not raw:
        return 0.0
    try:
        pace = float(raw)
    except ValueError as exc:
        raise ValueError(f"{PACE_ENV} must be a number of seconds, got {raw!r}") from exc
    return max(pace, 0.0)


def retry_after_seconds(exc: HttpResponseError) -> Optional[float]:
    headers = getattr(getattr(exc, "response", None), "headers", None) or {}
    for key, value in headers.items():
        if str(key).lower() == "retry-after":
            try:
                return max(float(value), 0.0)
            except ValueError:
                return None
    return None


def list_once_with_throttle_retry(list_call: Callable[[], Any], account: str) -> list:
    """Materialize a per-account listing; on a 429 wait Retry-After once and retry once."""
    try:
        return list(list_call())
    except HttpResponseError as exc:
        delay = retry_after_seconds(exc) if exc.status_code == 429 else None
        if delay is None:
            raise
        log.warning("Storage RP throttled account %s (429); retrying once after %.0fs", account, delay)
        time.sleep(delay)
        return list(list_call())


def _iter_accounts(client):
    for acct in client.storage_accounts.list():
        rg = utils.extract_resource_group(acct.id)
        yield rg, acct.name


def main(subscription_id: str, subscription_name: str) -> utils.ExportResult:
    environment = utils.detect_environment()
    if not utils.is_service_available_in_environment("storage", environment):
        sys.exit(0)

    client = utils.get_azure_client("storage", subscription_id)
    log.info("Listing blob containers across storage accounts in %s", subscription_id)
    pace = list_pace_seconds()

    rows = []
    errors: list = []
    for index, (rg, account) in enumerate(_iter_accounts(client)):
        if pace and index:
            time.sleep(pace)
        try:
            containers = list_once_with_throttle_retry(
                partial(client.blob_containers.list, rg, account), account
            )
        except HttpResponseError as e:
            errors.append(utils.error_record(account, "blob_containers.list", e))
            log.warning("Failed to list containers for account %s: %s", account, e)
            continue
        for c in containers:
            metadata = getattr(c, "metadata", None) or {}
            rows.append({
                "Storage Account": account,
                "Container Name": c.name,
                "Resource Group": rg,
                "Public Access Level": utils.s(getattr(c, "public_access", None)) if getattr(c, "public_access", None) else "None",
                "Lease State": utils.s(getattr(c, "lease_state", None)) if getattr(c, "lease_state", None) else "",
                "Has Immutability Policy": "Yes" if getattr(c, "has_immutability_policy", False) else "No",
                "Has Legal Hold": "Yes" if getattr(c, "has_legal_hold", False) else "No",
                "Default Encryption Scope": getattr(c, "default_encryption_scope", "") or "",
                "Last Modified": utils.s(getattr(c, "last_modified_time", None)) if getattr(c, "last_modified_time", None) else "",
                "Metadata": "; ".join(f"{k}={v}" for k, v in metadata.items()),
            })

    if not rows and not errors:
        raise utils.NoResourcesFound("blob containers")

    df = pd.DataFrame(rows)
    filename = utils.create_export_filename(subscription_name, "blob-containers", "all")
    utils.save_dataframe_to_excel(df, filename, sheet_name="Blob Containers", errors=errors)
    print(f"Exported {len(rows)} blob container(s) → {filename}")
    log.info("Export complete: %d containers", len(rows))
    return utils.ExportResult(rows=len(rows), filename=filename, errors=errors)


if __name__ == "__main__":
    import runner

    runner.run_exporter(main, "blob-containers")
