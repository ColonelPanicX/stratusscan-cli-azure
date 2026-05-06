"""
sslib.subscriptions — Subscription and tenant enumeration.
"""

import logging
from typing import Dict, List

from azure.mgmt.subscription import SubscriptionClient

logger = logging.getLogger(__name__)


def list_subscriptions(credential) -> List[Dict[str, str]]:
    """
    List all subscriptions accessible to the signed-in identity.

    Returns:
        list of dicts: [{id, name, tenant_id, state}]
    """
    client = SubscriptionClient(credential)
    subs = []
    for sub in client.subscriptions.list():
        # tenant_id is on Tenant, not Subscription, in azure-mgmt-subscription;
        # use getattr() so older azure-mgmt-resource-derived models (which did
        # expose it) keep working transparently.
        subs.append(
            {
                "id": sub.subscription_id,
                "name": sub.display_name,
                "tenant_id": getattr(sub, "tenant_id", "") or "",
                "state": str(sub.state),
            }
        )
    logger.info("Discovered %d subscription(s)", len(subs))
    return subs


def list_tenants(credential) -> List[Dict[str, str]]:
    """
    List tenants the signed-in identity has access to.
    """
    client = SubscriptionClient(credential)
    tenants = []
    for t in client.tenants.list():
        tenants.append(
            {
                "id": t.tenant_id,
                "name": getattr(t, "display_name", "") or "",
                "default_domain": getattr(t, "default_domain", "") or "",
            }
        )
    return tenants


def filter_subscription_ids(
    subscriptions: List[Dict[str, str]],
    config: Dict,
) -> List[str]:
    """
    Apply the user's `default_scope` from config.json to the subscription list.

    mode='all'         → every Enabled subscription
    mode='selected'    → only IDs in selected_subscription_ids
    """
    scope = config.get("default_scope", {}) if config else {}
    mode = scope.get("mode", "all")

    if mode == "selected":
        wanted = set(scope.get("selected_subscription_ids", []))
        return [s["id"] for s in subscriptions if s["id"] in wanted]

    return [s["id"] for s in subscriptions if s.get("state", "").lower().endswith("enabled")]
