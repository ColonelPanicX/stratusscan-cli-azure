#!/usr/bin/env python3
"""
StratusScan-Azure — Microsoft Entra ID (Azure AD) export.

Pulls users, groups, applications, service principals, directory roles, and
conditional-access policies via the Microsoft Graph REST API.

Required Graph permissions (delegated, granted to the signed-in user):
    User.Read.All, Group.Read.All, Application.Read.All,
    Directory.Read.All, Policy.Read.All

Cloud Shell users typically already have these via their AAD role; if a 403
comes back, escalate the relevant directory role or have an admin grant
delegated consent.
"""

import logging
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

# Allow running as a script from /scripts/
_root = Path(__file__).parent.parent
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

from sslib.auth import get_credential, get_graph_token, quiet_azure_loggers
from sslib.cloud import detect_cloud, graph_scope_for_cloud
from sslib.config import load_config
from sslib.output import make_filename, save_dataframes, snapshot_metadata

logger = logging.getLogger(__name__)


def graph_get_all(token: str, base: str, path: str, params: Optional[Dict] = None) -> List[Dict]:
    """
    GET a Microsoft Graph collection endpoint, following @odata.nextLink to exhaustion.

    Handles 429 (Retry-After) and transient 5xx with exponential backoff.
    """
    import time

    import requests

    url = f"{base}/v1.0{path}"
    if params:
        from urllib.parse import urlencode
        url = f"{url}?{urlencode(params)}"

    headers = {"Authorization": f"Bearer {token}"}
    items: List[Dict] = []

    while url:
        for attempt in range(5):
            resp = requests.get(url, headers=headers, timeout=60)
            if resp.status_code == 429:
                wait = int(resp.headers.get("Retry-After", "5"))
                logger.warning("Graph 429 on %s — sleeping %ds (attempt %d)", path, wait, attempt + 1)
                time.sleep(wait)
                continue
            if 500 <= resp.status_code < 600:
                wait = 2 ** attempt
                logger.warning("Graph %d on %s — backing off %ds", resp.status_code, path, wait)
                time.sleep(wait)
                continue
            break
        else:
            logger.error("Graph %s exhausted retries", path)
            return items

        if resp.status_code == 403:
            logger.warning("403 from %s — missing directory permissions; skipping", path)
            return items
        resp.raise_for_status()
        body = resp.json()
        items.extend(body.get("value", []))
        url = body.get("@odata.nextLink")

    logger.info("Graph %s → %d item(s)", path, len(items))
    return items


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    quiet_azure_loggers()

    try:
        import pandas as pd
    except ImportError:
        print("ERROR: pandas is required. Install with: pip install --user pandas openpyxl")
        return 1

    config = load_config()
    credential = get_credential()

    cloud = detect_cloud()
    base = cloud["graph_endpoint"]
    scope = graph_scope_for_cloud()
    print(f"Microsoft Graph endpoint: {base}")

    try:
        token = get_graph_token(credential, scope)
    except Exception as e:
        print(f"ERROR: failed to acquire Graph token ({e}). "
              "Make sure your account has directory read access.")
        return 1

    sheets: Dict[str, "pd.DataFrame"] = {}
    summary = []

    pulls = [
        ("Users", "/users",
         {"$select": "id,userPrincipalName,displayName,mail,accountEnabled,userType,createdDateTime,jobTitle,department,companyName"}),
        ("Groups", "/groups",
         {"$select": "id,displayName,mailEnabled,securityEnabled,groupTypes,description,createdDateTime"}),
        ("Applications", "/applications",
         {"$select": "id,appId,displayName,createdDateTime,signInAudience,publisherDomain"}),
        ("Service Principals", "/servicePrincipals",
         {"$select": "id,appId,displayName,servicePrincipalType,accountEnabled,appOwnerOrganizationId"}),
        ("Directory Roles", "/directoryRoles",
         {"$select": "id,displayName,description,roleTemplateId"}),
        ("Conditional Access", "/identity/conditionalAccess/policies", None),
    ]

    for sheet, path, params in pulls:
        try:
            print(f"  • {sheet}...")
            rows = graph_get_all(token, base, path, params)
            df = pd.DataFrame(rows) if rows else pd.DataFrame()
            sheets[sheet] = df
            summary.append({"Sheet": sheet, "Path": path, "Rows": len(df)})
        except Exception as e:
            logger.error("Graph pull %s failed: %s", path, e)
            summary.append({"Sheet": sheet, "Path": path, "Rows": f"ERROR: {e}"})

    sheets = {
        "Snapshot": snapshot_metadata(config, cloud),
        "Summary": pd.DataFrame(summary),
        **sheets,
    }

    tenant = config.get("tenant_name", "AZURE-TENANT")
    filename = make_filename(tenant, "entra-id", "all")
    path = save_dataframes(sheets, filename)
    if path:
        print(f"\nWrote: {path}")
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
