"""
sslib.auth — Azure credential resolution.

Cloud Shell, dev box (`az login`), VM with managed identity, and CI with
service principal env vars all work without configuration.
"""

import logging
from typing import Optional

from azure.identity import (
    AzureCliCredential,
    ChainedTokenCredential,
    DefaultAzureCredential,
)

logger = logging.getLogger(__name__)


def get_credential() -> ChainedTokenCredential:
    """
    Return a credential chain optimized for Cloud Shell and dev workflows.

    Order:
      1. AzureCliCredential — instant in Cloud Shell, instant when `az login` is set up
      2. DefaultAzureCredential — managed identity, env-var SP, VS Code, etc.

    AzureCliCredential is tried first so Cloud Shell users avoid the
    managed-identity probe timeout that DefaultAzureCredential starts with.
    """
    return ChainedTokenCredential(
        AzureCliCredential(),
        DefaultAzureCredential(exclude_cli_credential=True),
    )


def quiet_azure_loggers() -> None:
    """
    Silence the Azure SDK's per-request HTTP logging (which is INFO level by
    default and dominates the terminal). Caller-side INFO logs still print.
    """
    for name in (
        "azure",
        "azure.core",
        "azure.core.pipeline.policies.http_logging_policy",
        "azure.identity",
        "azure.mgmt",
        "msal",
    ):
        logging.getLogger(name).setLevel(logging.WARNING)


def get_graph_token(credential, scope: str = "https://graph.microsoft.com/.default") -> str:
    """
    Return a bearer token for Microsoft Graph.

    For USGov use scope='https://graph.microsoft.us/.default'.
    """
    return credential.get_token(scope).token
