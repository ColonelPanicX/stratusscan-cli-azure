"""
sslib.cost_management — Azure Cost Management Query API helpers.

Pulls actual billed costs (post-RI, post-AHB, gov-cloud aware) per resource
from the Cost Management Query API. Used by the cost findings report to
attach $$ figures to inventory data from Resource Graph.

The signed-in identity needs the Cost Management Reader role on every
subscription queried (or any role that grants the
Microsoft.CostManagement/query/action operation). Without it the API
returns 403 — get_cost_by_resource() skips that subscription with a
warning and continues.

Raw REST is used here rather than the azure-mgmt-costmanagement SDK to
avoid a new runtime dependency (requests is already in use elsewhere) and
to keep error handling explicit per status code.
"""

from __future__ import annotations

import logging
import time
from typing import Dict, List, Optional

import requests

from sslib.cloud import arm_endpoint_for_cloud, arm_scope_for_cloud

logger = logging.getLogger(__name__)

_API_VERSION = "2023-11-01"

DEFAULT_TIMEFRAME = "TheLastMonth"


def _build_body(timeframe: str) -> dict:
    return {
        "type": "ActualCost",
        "timeframe": timeframe,
        "dataset": {
            "granularity": "None",
            "aggregation": {"totalCost": {"name": "Cost", "function": "Sum"}},
            "grouping": [{"type": "Dimension", "name": "ResourceId"}],
        },
    }


class _PermissionDenied(Exception):
    """Raised when Cost Management returns 403 for a subscription scope."""


def get_cost_by_resource(
    credential,
    subscription_ids: List[str],
    timeframe: str = DEFAULT_TIMEFRAME,
) -> Dict[str, float]:
    """
    Query Cost Management for actual costs grouped by ResourceId across the
    given subscriptions. Returns {resource_id_lower: cost} aggregated across
    all subscriptions. Currency is assumed consistent within a tenant; the
    Currency column is not surfaced.

    Subscriptions where the identity lacks Cost Management Reader role are
    skipped with a logged warning; the rest still return. An empty dict
    means no subscription returned cost data — the caller decides whether
    to fall back to size-only findings or to error out.
    """
    base_url = arm_endpoint_for_cloud()
    scope = arm_scope_for_cloud()

    costs: Dict[str, float] = {}
    denied: List[str] = []
    ok = 0

    for sub_id in subscription_ids:
        try:
            sub_costs = _query_subscription(credential, base_url, scope, sub_id, timeframe)
            costs.update(sub_costs)
            ok += 1
        except _PermissionDenied:
            denied.append(sub_id)
        except Exception as e:
            logger.error("Cost Management query failed for %s: %s", sub_id, e)

    if denied:
        logger.warning(
            "Cost Management 403 on %d subscription(s) — identity needs "
            "Cost Management Reader: %s",
            len(denied), ", ".join(denied),
        )
    logger.info(
        "Pulled cost data for %d resource(s) across %d/%d subscription(s)",
        len(costs), ok, len(subscription_ids),
    )
    return costs


def _query_subscription(
    credential,
    base_url: str,
    scope: str,
    sub_id: str,
    timeframe: str,
) -> Dict[str, float]:
    """
    Query Cost Management for a single subscription, paginating via
    nextLink. Raises _PermissionDenied on 403 so the caller can record-and-
    continue rather than aborting the whole run.
    """
    url: Optional[str] = (
        f"{base_url}/subscriptions/{sub_id}/providers/Microsoft.CostManagement/query"
        f"?api-version={_API_VERSION}"
    )
    body = _build_body(timeframe)
    costs: Dict[str, float] = {}

    while url:
        token = credential.get_token(scope).token
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }

        resp = None
        for attempt in range(5):
            resp = requests.post(url, headers=headers, json=body, timeout=120)
            if resp.status_code == 429:
                wait = int(resp.headers.get("Retry-After", "10"))
                logger.warning(
                    "Cost Management 429 for %s — sleeping %ds (attempt %d)",
                    sub_id, wait, attempt + 1,
                )
                time.sleep(wait)
                continue
            if 500 <= resp.status_code < 600:
                wait = 2 ** attempt
                logger.warning(
                    "Cost Management %d for %s — backing off %ds",
                    resp.status_code, sub_id, wait,
                )
                time.sleep(wait)
                continue
            break
        else:
            logger.error("Cost Management exhausted retries for %s", sub_id)
            return costs

        assert resp is not None
        if resp.status_code == 403:
            raise _PermissionDenied(resp.text[:300])
        resp.raise_for_status()

        result = resp.json()
        props = result.get("properties") or {}
        columns = props.get("columns") or []
        rows = props.get("rows") or []

        col_names = [c.get("name") for c in columns]
        try:
            cost_idx = col_names.index("Cost")
            resource_idx = col_names.index("ResourceId")
        except ValueError:
            logger.warning(
                "Unexpected Cost Management response shape for %s: cols=%s",
                sub_id, col_names,
            )
            return costs

        for row in rows:
            if len(row) <= max(cost_idx, resource_idx):
                continue
            rid = row[resource_idx]
            cost = row[cost_idx]
            if rid is None or cost is None:
                continue
            rid_key = str(rid).lower()
            costs[rid_key] = costs.get(rid_key, 0.0) + float(cost)

        url = props.get("nextLink") or None

    return costs
