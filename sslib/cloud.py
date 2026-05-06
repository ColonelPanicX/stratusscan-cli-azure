"""
sslib.cloud — Detect the active Azure cloud (Public / USGov / China).

The active cloud governs ARM endpoints and Microsoft Graph endpoints.
Cloud Shell and dev boxes set this via `az cloud set`, so we read from
the Azure CLI's reported state.
"""

import json
import logging
import subprocess
from typing import Dict, Optional

logger = logging.getLogger(__name__)

# Microsoft Graph endpoints by cloud — used for Entra ID exports
GRAPH_ENDPOINTS = {
    "AzureCloud": "https://graph.microsoft.com",
    "AzureUSGovernment": "https://graph.microsoft.us",
    "AzureChinaCloud": "https://microsoftgraph.chinacloudapi.cn",
}


def detect_cloud() -> Dict[str, str]:
    """
    Return the active cloud info from `az cloud show`.

    Returns a dict with keys: name, graph_endpoint. Falls back to AzureCloud
    if `az` is not installed or the call fails.
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
    }


def is_government_cloud() -> bool:
    return detect_cloud()["name"] == "AzureUSGovernment"


def graph_scope_for_cloud() -> str:
    """Return the Microsoft Graph .default scope for the active cloud."""
    endpoint = detect_cloud()["graph_endpoint"]
    return f"{endpoint}/.default"
