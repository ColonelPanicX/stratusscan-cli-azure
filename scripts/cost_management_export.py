#!/usr/bin/env python3
"""StratusScanCLI-Azure — Cost Management Export (month-to-date actual cost)

One Query API POST per page. The Query API is not an ARM list: it returns a single
QueryResult whose nextLink must be re-POSTed with the same body, it answers 204
when the scope has no cost rows, and it is rate-limited in query processing units
(12 QPU / 10 s, 60 / min, 600 / hr per tenant). azure-core's RetryPolicy retries a
POST only on 500/503/504 or when a standard Retry-After header is present, so a
429 carrying only x-ms-ratelimit-microsoft.costmanagement-qpu-retry-after is
retried here, bounded, honoring that header.
"""

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
from azure.core.rest import HttpRequest

utils.setup_logging("cost-management-export")
utils.log_script_start("cost_management_export.py", "Azure Cost Management Export")

log = utils.get_logger()

TIMEFRAME = "MonthToDate"

_QUERY = {
    "type": "ActualCost",
    "timeframe": TIMEFRAME,
    "dataset": {
        "granularity": "None",
        "aggregation": {"totalCost": {"name": "PreTaxCost", "function": "Sum"}},
        "grouping": [
            {"type": "Dimension", "name": "ResourceGroup"},
            {"type": "Dimension", "name": "ServiceName"},
        ],
    },
}

QPU_RETRY_AFTER_HEADER = "x-ms-ratelimit-microsoft.costmanagement-qpu-retry-after"
STANDARD_RETRY_AFTER_HEADER = "retry-after"
MAX_ATTEMPTS = 3
DEFAULT_THROTTLE_PAUSE_S = 10.0


def _header(headers: Any, name: str) -> Optional[str]:
    for key, value in (headers or {}).items():
        if str(key).lower() == name:
            return str(value)
    return None


def throttle_delay(exc: HttpResponseError) -> Optional[float]:
    """Seconds to wait before re-issuing a 429 the SDK did not retry; None when this exporter must not retry it."""
    if getattr(exc, "status_code", None) != 429:
        return None
    headers = getattr(getattr(exc, "response", None), "headers", None)
    if _header(headers, STANDARD_RETRY_AFTER_HEADER) is not None:
        return None
    qpu_retry_after = _header(headers, QPU_RETRY_AFTER_HEADER)
    try:
        return float(qpu_retry_after) if qpu_retry_after else DEFAULT_THROTTLE_PAUSE_S
    except ValueError:
        return DEFAULT_THROTTLE_PAUSE_S


def call_with_throttle_retry(operation: Callable[[], Any], describe: str) -> Any:
    attempt = 1
    while True:
        try:
            return operation()
        except HttpResponseError as exc:
            delay = throttle_delay(exc)
            if delay is None or attempt >= MAX_ATTEMPTS:
                raise
            log.warning(
                "Cost Management throttled %s (429); waiting %.0fs before attempt %d/%d",
                describe, delay, attempt + 1, MAX_ATTEMPTS,
            )
            time.sleep(delay)
            attempt += 1


def _next_page(client, next_link: str):
    """Re-POST the query body to nextLink; the SDK exposes no pager for QueryResult."""
    from azure.mgmt.costmanagement.models import QueryResult

    response = client.send_request(HttpRequest("POST", next_link, json=_QUERY))
    if response.status_code == 204:
        return None
    if response.status_code != 200:
        raise HttpResponseError(response=response)
    return QueryResult(response.json())


def _page_rows(result, scope: str) -> list:
    columns = [getattr(c, "name", "") for c in (result.columns or [])]
    rows = []
    for raw in result.rows or []:
        row = dict(zip(columns, raw))
        row.setdefault("Currency", "")
        row["Scope"] = scope
        row["Timeframe"] = TIMEFRAME
        rows.append(row)
    return rows


def collect_costs(subscription_id: str, errors: list) -> list:
    client = utils.get_azure_client("costmanagement")
    scope = f"/subscriptions/{subscription_id}"
    log.info("Querying month-to-date cost for subscription %s", subscription_id)

    result = call_with_throttle_retry(
        lambda: client.query.usage(scope=scope, parameters=_QUERY), "query.usage"
    )
    if result is None:
        return []

    rows = _page_rows(result, scope)
    page = 1
    next_link = result.next_link
    while next_link:
        page += 1
        try:
            result = call_with_throttle_retry(
                partial(_next_page, client, next_link), f"query.usage page {page}"
            )
        except HttpResponseError as exc:
            errors.append(utils.error_record(f"{scope} page {page}", "query.usage(nextLink)", exc))
            log.warning("Cost query page %d failed; export is truncated: %s", page, exc)
            break
        if result is None:
            break
        rows.extend(_page_rows(result, scope))
        next_link = result.next_link
    log.info("Cost query returned %d rows over %d page(s)", len(rows), page)
    return rows


def main(subscription_id: str, subscription_name: str) -> utils.ExportResult:
    environment = utils.detect_environment()
    if not utils.is_service_available_in_environment("costmanagement", environment):
        sys.exit(0)

    errors: list = []
    rows = collect_costs(subscription_id, errors)

    if not rows and not errors:
        raise utils.NoResourcesFound("cost data")

    df = pd.DataFrame(rows)
    filename = utils.create_export_filename(subscription_name, "cost-management", "mtd")
    utils.save_dataframe_to_excel(df, filename, errors=errors)
    print(f"Exported {len(rows)} cost row(s) → {filename}")
    log.info("Export complete: %d cost rows", len(rows))
    return utils.ExportResult(rows=len(rows), filename=filename, errors=errors)


if __name__ == "__main__":
    import runner

    runner.run_exporter(main, "cost-management")
