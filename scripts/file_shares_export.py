#!/usr/bin/env python3
"""StratusScanCLI-Azure — File Shares Inventory Export

One file_shares.list call per storage account. The Storage resource provider
allows 100 list operations per 5 minutes per subscription per region, so a
subscription with many accounts in one region can be throttled mid-run. A 429 is
retried once after the Retry-After the service asks for; a second 429, or a 429
without Retry-After, is recorded for that account (PARTIAL) rather than dropped.
STRATUSSCAN_STORAGE_LIST_PACE_S (seconds, default 0) spaces the per-account calls.
"""

import os
import sys
import time
from collections.abc import Callable
from functools import partial
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


def retry_after_seconds(exc: HttpResponseError) -> float | None:
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
        yield utils.extract_resource_group(acct.id), acct.name


def _build_row(share, account: str, rg: str) -> dict:
    return {
        "Storage Account": account,
        "Share Name": share.name,
        "Resource Group": rg,
        "Access Tier": utils.s(share.access_tier),
        "Quota GB": share.share_quota if share.share_quota is not None else "",
        "Enabled Protocols": utils.s(share.enabled_protocols),
        "Root Squash": utils.s(share.root_squash),
        "Lease State": utils.s(share.lease_state),
        "Lease Status": utils.s(share.lease_status),
    }


def main(subscription_id: str, subscription_name: str) -> utils.ExportResult:
    environment = utils.detect_environment()
    if not utils.is_service_available_in_environment("storage", environment):
        sys.exit(0)

    client = utils.get_azure_client("storage", subscription_id)
    log.info("Listing file shares across storage accounts in %s", subscription_id)
    pace = list_pace_seconds()

    rows = []
    errors: list = []
    unsupported_accounts = 0
    for index, (rg, account) in enumerate(_iter_accounts(client)):
        if pace and index:
            time.sleep(pace)
        try:
            shares = list_once_with_throttle_retry(
                partial(client.file_shares.list, rg, account), account
            )
        except HttpResponseError as e:
            if utils.error_code(e) == "FeatureNotSupportedForAccount":
                unsupported_accounts += 1
                log.info("Skipping file shares for unsupported account %s", account)
                continue
            errors.append(utils.error_record(account, "file_shares.list", e))
            log.warning("Failed to list file shares for account %s: %s", account, e)
            continue
        for share in shares:
            rows.append(_build_row(share, account, rg))

    if unsupported_accounts:
        print(f"Skipped {unsupported_accounts} account(s) that do not support Azure Files.")

    if not rows and not errors:
        raise utils.NoResourcesFound("file shares")

    df = pd.DataFrame(rows)
    filename = utils.create_export_filename(subscription_name, "file-shares", "all")
    utils.save_dataframe_to_excel(df, filename, sheet_name="File Shares", errors=errors)
    print(f"Exported {len(rows)} file share(s) → {filename}")
    log.info("Export complete: %d file shares", len(rows))
    return utils.ExportResult(rows=len(rows), filename=filename, errors=errors)


if __name__ == "__main__":
    import runner

    runner.run_exporter(main, "file-shares")
