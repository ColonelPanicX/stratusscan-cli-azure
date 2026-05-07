"""
sslib.cloud — Detect the active Azure cloud (Public / USGov).

The active cloud governs ARM endpoints and Microsoft Graph endpoints.
Cloud Shell and dev boxes set this via `az cloud set`, so we read from
the Azure CLI's reported state.
"""

import json
import logging
import subprocess
from functools import lru_cache
from typing import Dict, List

logger = logging.getLogger(__name__)

GRAPH_ENDPOINTS = {
    "AzureCloud": "https://graph.microsoft.com",
    "AzureUSGovernment": "https://graph.microsoft.us",
}

ARM_ENDPOINTS = {
    "AzureCloud": "https://management.azure.com",
    "AzureUSGovernment": "https://management.usgovcloudapi.net",
}


@lru_cache(maxsize=1)
def detect_cloud() -> Dict[str, str]:
    """
    Return the active cloud info from `az cloud show`.

    Returns a dict with keys: name, graph_endpoint, arm_endpoint. Falls back
    to AzureCloud if `az` is not installed or the call fails.

    Cached for the process lifetime — subprocess invocation is expensive and
    the active cloud doesn't change without restarting the session.
    """
    name = "AzureCloud"
    try:
        result = subprocess.run(
            ["az", "cloud", "show", "-o", "json"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        if result.returncode == 0:
            data = json.loads(result.stdout)
            name = data.get("name", "AzureCloud")
    except FileNotFoundError:
        logger.debug("az CLI not found — defaulting to AzureCloud")
    except (subprocess.TimeoutExpired, json.JSONDecodeError) as e:
        logger.debug("az cloud show failed (%s) — defaulting to AzureCloud", e)

    return {
        "name": name,
        "graph_endpoint": GRAPH_ENDPOINTS.get(name, GRAPH_ENDPOINTS["AzureCloud"]),
        "arm_endpoint": ARM_ENDPOINTS.get(name, ARM_ENDPOINTS["AzureCloud"]),
    }


def is_government_cloud() -> bool:
    return detect_cloud()["name"] == "AzureUSGovernment"


def graph_scope_for_cloud() -> str:
    """Microsoft Graph .default scope for the active cloud."""
    return f"{detect_cloud()['graph_endpoint']}/.default"


def arm_endpoint_for_cloud() -> str:
    """ARM management endpoint for the active cloud."""
    return detect_cloud()["arm_endpoint"]


def arm_scope_for_cloud() -> str:
    """ARM .default scope for the active cloud."""
    return f"{detect_cloud()['arm_endpoint']}/.default"


def arm_client_kwargs() -> Dict[str, object]:
    """
    Keyword args to splat into any azure-mgmt-* client constructor so it
    routes to the active cloud's ARM endpoint.

    Example:
        client = ResourceGraphClient(credential, **arm_client_kwargs())
    """
    arm = arm_endpoint_for_cloud()
    return {"base_url": arm, "credential_scopes": [f"{arm}/.default"]}
