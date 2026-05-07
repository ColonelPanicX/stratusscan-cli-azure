#!/usr/bin/env python3
"""
StratusScan-Azure — Resource Graph export.

Pulls a comprehensive snapshot of every ARM resource visible to the signed-in
identity using Azure Resource Graph. One Excel file per run, with sheets for
each Resource Graph table queried. This single script covers the bulk of
"everything in Azure" — supplement with entra_id_export, rbac_export, and
policy_export for things outside the ARM data plane.

Tables queried:
    - Resources              (all ARM resources: VMs, storage, networks, KVs, etc.)
    - ResourceContainers     (subscriptions, resource groups, management groups)
    - AdvisorResources       (Azure Advisor recommendations)
    - SecurityResources      (Defender for Cloud assessments)
    - PolicyResources        (Policy assignments + compliance state)
    - HealthResources        (Service health events)
    - AuthorizationResources (RBAC role assignments — also pulled deeper by rbac_export)
"""

import logging
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

# Allow running as a script from /scripts/
_root = Path(__file__).parent.parent
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

from sslib.auth import get_credential, quiet_azure_loggers
from sslib.cloud import arm_client_kwargs, detect_cloud
from sslib.config import load_config, resolve_scope_label
from sslib.output import make_filename, save_dataframes, snapshot_metadata
from sslib.subscriptions import filter_subscription_ids, list_subscriptions

logger = logging.getLogger(__name__)


# Each entry: (sheet_name, kql_query)
# Top-level + subscriptionId where relevant so the user can pivot.
DEFAULT_QUERIES: List[Dict[str, str]] = [
    {
        "sheet": "All Resources",
        "table": "Resources",
        "query": (
            "Resources | project subscriptionId, resourceGroup, name, type, "
            "kind, location, "
            "skuName=tostring(sku.name), skuTier=tostring(sku.tier), "
            "identityType=tostring(identity.type), "
            "zones=tostring(zones), managedBy, tags=tostring(tags), id"
        ),
    },
    {
        "sheet": "Containers",
        "table": "ResourceContainers",
        "query": (
            "ResourceContainers | project subscriptionId, type, name, "
            "tenantId, location, id"
        ),
    },
    {
        "sheet": "Subnets",
        "table": "Resources",
        "query": (
            "Resources | where type =~ 'microsoft.network/virtualnetworks' "
            "| mv-expand subnet=properties.subnets "
            "| project subscriptionId, resourceGroup, vnetName=name, location, "
            "subnetName=tostring(subnet.name), "
            "addressPrefix=tostring(subnet.properties.addressPrefix), "
            "addressPrefixes=tostring(subnet.properties.addressPrefixes), "
            "nsgId=tostring(subnet.properties.networkSecurityGroup.id), "
            "routeTableId=tostring(subnet.properties.routeTable.id), "
            "natGatewayId=tostring(subnet.properties.natGateway.id), "
            "delegations=tostring(subnet.properties.delegations), "
            "serviceEndpoints=tostring(subnet.properties.serviceEndpoints), "
            "privateEndpointNetworkPolicies=tostring(subnet.properties.privateEndpointNetworkPolicies), "
            "id=strcat(id, '/subnets/', tostring(subnet.name))"
        ),
    },
    {
        "sheet": "VNet Peerings",
        "table": "Resources",
        "query": (
            "Resources | where type =~ 'microsoft.network/virtualnetworks' "
            "| mv-expand peering=properties.virtualNetworkPeerings "
            "| where isnotnull(peering) "
            "| project subscriptionId, resourceGroup, vnetName=name, location, "
            "peeringName=tostring(peering.name), "
            "peeringState=tostring(peering.properties.peeringState), "
            "remoteVnetId=tostring(peering.properties.remoteVirtualNetwork.id), "
            "allowVirtualNetworkAccess=tobool(peering.properties.allowVirtualNetworkAccess), "
            "allowForwardedTraffic=tobool(peering.properties.allowForwardedTraffic), "
            "allowGatewayTransit=tobool(peering.properties.allowGatewayTransit), "
            "useRemoteGateways=tobool(peering.properties.useRemoteGateways), "
            "id=strcat(id, '/peerings/', tostring(peering.name))"
        ),
    },
    {
        "sheet": "SQL Databases",
        "table": "Resources",
        "query": (
            "Resources | where type =~ 'microsoft.sql/servers/databases' "
            "| project subscriptionId, resourceGroup, "
            "serverName=tostring(split(id, '/')[8]), name, location, "
            "skuName=tostring(sku.name), skuTier=tostring(sku.tier), "
            "status=tostring(properties.status), "
            "collation=tostring(properties.collation), "
            "maxSizeBytes=tolong(properties.maxSizeBytes), "
            "zoneRedundant=tobool(properties.zoneRedundant), id"
        ),
    },
    {
        "sheet": "Storage Containers",
        "table": "Resources",
        "query": (
            "Resources | where type =~ 'microsoft.storage/storageaccounts/blobservices/containers' "
            "| project subscriptionId, resourceGroup, "
            "storageAccount=tostring(split(id, '/')[8]), "
            "containerName=name, "
            "publicAccess=tostring(properties.publicAccess), "
            "hasImmutabilityPolicy=tobool(properties.hasImmutabilityPolicy), "
            "hasLegalHold=tobool(properties.hasLegalHold), "
            "leaseStatus=tostring(properties.leaseStatus), "
            "leaseState=tostring(properties.leaseState), id"
        ),
    },
    {
        "sheet": "Resource Locks",
        "table": "Resources",
        "query": (
            "Resources | where type =~ 'microsoft.authorization/locks' "
            "| project subscriptionId, resourceGroup, name, "
            "level=tostring(properties.level), "
            "notes=tostring(properties.notes), id"
        ),
    },
    {
        "sheet": "Advisor Recommendations",
        "table": "AdvisorResources",
        "query": (
            "AdvisorResources | where type == 'microsoft.advisor/recommendations' "
            "| project subscriptionId, resourceGroup, name, "
            "category=tostring(properties.category), "
            "impact=tostring(properties.impact), "
            "problem=tostring(properties.shortDescription.problem), "
            "solution=tostring(properties.shortDescription.solution), "
            "impactedField=tostring(properties.impactedField), "
            "impactedValue=tostring(properties.impactedValue), id"
        ),
    },
    {
        "sheet": "Defender Assessments",
        "table": "SecurityResources",
        "query": (
            "SecurityResources | where type == 'microsoft.security/assessments' "
            "| project subscriptionId, resourceGroup, name, "
            "displayName=tostring(properties.displayName), "
            "status=tostring(properties.status.code), "
            "severity=tostring(properties.metadata.severity), "
            "category=tostring(properties.metadata.categories), "
            "resourceId=tostring(properties.resourceDetails.Id), id"
        ),
    },
    {
        "sheet": "Policy Compliance",
        "table": "PolicyResources",
        "query": (
            "PolicyResources | where type == 'microsoft.policyinsights/policystates' "
            "| project subscriptionId, resourceGroup, "
            "policyAssignmentName=tostring(properties.policyAssignmentName), "
            "policyDefinitionName=tostring(properties.policyDefinitionName), "
            "complianceState=tostring(properties.complianceState), "
            "resourceId=tostring(properties.resourceId), "
            "resourceType=tostring(properties.resourceType), "
            "timestamp=tostring(properties.timestamp)"
        ),
    },
    {
        "sheet": "Service Health",
        "table": "HealthResources",
        "query": (
            "HealthResources | project subscriptionId, resourceGroup, type, name, "
            "location, "
            "eventType=tostring(properties.eventType), "
            "status=tostring(properties.status), "
            "summary=tostring(properties.summary), id"
        ),
    },
    {
        "sheet": "Role Assignments (RG view)",
        "table": "AuthorizationResources",
        "query": (
            "AuthorizationResources | where type == 'microsoft.authorization/roleassignments' "
            "| project subscriptionId, "
            "principalId=tostring(properties.principalId), "
            "principalType=tostring(properties.principalType), "
            "roleDefinitionId=tostring(properties.roleDefinitionId), "
            "scope=tostring(properties.scope), id"
        ),
    },
]


def run_query(
    credential,
    subscription_ids: List[str],
    query: str,
    page_size: int = 1000,
) -> List[Dict[str, Any]]:
    """
    Execute a Resource Graph KQL query, paginating until exhausted.

    Returns a list of dicts. Resource Graph caps at 1000 rows per page;
    we follow skip_token until the API stops returning one.
    """
    from azure.mgmt.resourcegraph import ResourceGraphClient
    from azure.mgmt.resourcegraph.models import QueryRequest, QueryRequestOptions

    client = ResourceGraphClient(credential, **arm_client_kwargs())
    rows: List[Dict[str, Any]] = []
    skip_token: Optional[str] = None
    page = 0

    while True:
        page += 1
        options = QueryRequestOptions(top=page_size, skip_token=skip_token)
        request = QueryRequest(
            subscriptions=subscription_ids,
            query=query,
            options=options,
        )
        response = client.resources(request)
        page_data = response.data or []
        # response.data is normally a list[dict] when result_format defaults to objectArray
        if isinstance(page_data, dict) and "rows" in page_data:
            # tabular fallback — unlikely with default format but handle gracefully
            cols = [c.get("name") for c in page_data.get("columns", [])]
            page_data = [dict(zip(cols, row)) for row in page_data.get("rows", [])]
        rows.extend(page_data)

        skip_token = getattr(response, "skip_token", None)
        if not skip_token:
            break

    logger.info("Query returned %d row(s) across %d page(s)", len(rows), page)
    return rows


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

    print("Discovering subscriptions...")
    subs = list_subscriptions(credential)
    if not subs:
        print("No subscriptions found for the signed-in identity.")
        return 1

    sub_ids = filter_subscription_ids(subs, config)
    if not sub_ids:
        print("No subscriptions selected after applying default_scope filter.")
        return 1

    print(f"Querying {len(sub_ids)} subscription(s) across {len(DEFAULT_QUERIES)} table(s)...")

    sheets: Dict[str, "pd.DataFrame"] = {}
    summary_rows = []

    for q in DEFAULT_QUERIES:
        sheet = q["sheet"]
        try:
            print(f"  • {sheet} ({q['table']})...")
            rows = run_query(credential, sub_ids, q["query"])
            df = pd.DataFrame(rows) if rows else pd.DataFrame()
            sheets[sheet] = df
            summary_rows.append(
                {"Sheet": sheet, "Table": q["table"], "Rows": len(df)}
            )
        except Exception as e:
            logger.error("Query for %s failed: %s", sheet, e)
            summary_rows.append(
                {"Sheet": sheet, "Table": q["table"], "Rows": f"ERROR: {e}"}
            )

    sheets = {
        "Snapshot": snapshot_metadata(config, detect_cloud(), sub_count=len(sub_ids)),
        "Summary": pd.DataFrame(summary_rows),
        **sheets,
    }

    filename = make_filename(resolve_scope_label(config, sub_ids), "resource-graph", "all")
    path = save_dataframes(sheets, filename)
    if path:
        print(f"\nWrote: {path}")
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
