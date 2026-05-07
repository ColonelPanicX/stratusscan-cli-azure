#!/usr/bin/env python3
"""
StratusScan-Azure — Resource Graph export.

Pulls a comprehensive snapshot of every ARM resource visible to the signed-in
identity using Azure Resource Graph. One Excel file per run, with sheets for
each Resource Graph table queried. This single script covers the bulk of
"everything in Azure" — supplement with entra_id_export, rbac_export, and
policy_export for things outside the ARM data plane.

Tables queried:
    - Resources                  (all ARM resources: VMs, disks, networks, KVs, etc.)
    - ResourceContainers         (subscriptions, resource groups, management groups)
    - AdvisorResources           (Azure Advisor recommendations)
    - SecurityResources          (Defender for Cloud assessments)
    - PolicyResources            (Policy assignments + compliance state)
    - HealthResources            (Service health events)
    - AuthorizationResources     (RBAC role assignments — also pulled deeper by rbac_export)
    - MaintenanceResources       (planned-maintenance updates)
    - PatchAssessmentResources   (pending OS patches per VM)

Dedicated sheets per resource type: Virtual Machines, Disks, AKS Clusters,
App Services, Network Interfaces, Public IPs, Network Security Groups,
Load Balancers, Subnets, VNet Peerings, SQL Databases, Cosmos DB Accounts,
Storage Accounts, Storage Containers, Key Vaults, Resource Locks.

A "Coverage Audit" sheet at the end groups every type present in the tenant
and flags which ones only land in "All Resources" — i.e. where adding a
dedicated sheet would yield richer projections.
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
        "sheet": "Virtual Machines",
        "table": "Resources",
        "query": (
            "Resources | where type =~ 'microsoft.compute/virtualmachines' "
            "| extend nicArray = properties.networkProfile.networkInterfaces "
            "| extend nicIds = strcat_array("
            "    extract_all(\"\\\"id\\\":\\\"([^\\\"]+)\\\"\", tostring(nicArray)), '; ') "
            "| project subscriptionId, resourceGroup, name, location, "
            "zones=tostring(zones), "
            "vmSize=tostring(properties.hardwareProfile.vmSize), "
            "osType=tostring(properties.storageProfile.osDisk.osType), "
            "imagePublisher=tostring(properties.storageProfile.imageReference.publisher), "
            "imageOffer=tostring(properties.storageProfile.imageReference.offer), "
            "imageSku=tostring(properties.storageProfile.imageReference.sku), "
            "imageVersion=tostring(properties.storageProfile.imageReference.version), "
            "osDiskName=tostring(properties.storageProfile.osDisk.name), "
            "osDiskSizeGB=toint(properties.storageProfile.osDisk.diskSizeGB), "
            "osDiskType=tostring(properties.storageProfile.osDisk.managedDisk.storageAccountType), "
            "dataDiskCount=array_length(properties.storageProfile.dataDisks), "
            "nicIds, "
            "availabilitySetId=tostring(properties.availabilitySet.id), "
            "priority=tostring(properties.priority), "
            "evictionPolicy=tostring(properties.evictionPolicy), "
            "licenseType=tostring(properties.licenseType), "
            "bootDiagnostics=tostring(properties.diagnosticsProfile.bootDiagnostics.enabled), "
            "powerState=tostring(properties.extended.instanceView.powerState.code), "
            "provisioningState=tostring(properties.provisioningState), "
            "vmId=tostring(properties.vmId), "
            "identityType=tostring(identity.type), "
            "tags=tostring(tags), id"
        ),
    },
    {
        "sheet": "Disks",
        "table": "Resources",
        "query": (
            "Resources | where type =~ 'microsoft.compute/disks' "
            "| project subscriptionId, resourceGroup, name, location, "
            "skuName=tostring(sku.name), skuTier=tostring(sku.tier), "
            "diskSizeGB=toint(properties.diskSizeGB), "
            "diskState=tostring(properties.diskState), "
            "osType=tostring(properties.osType), "
            "createOption=tostring(properties.creationData.createOption), "
            "encryptionType=tostring(properties.encryption.type), "
            "diskEncryptionSetId=tostring(properties.encryption.diskEncryptionSetId), "
            "networkAccessPolicy=tostring(properties.networkAccessPolicy), "
            "publicNetworkAccess=tostring(properties.publicNetworkAccess), "
            "managedBy=tostring(managedBy), "
            "tags=tostring(tags), id"
        ),
    },
    {
        "sheet": "AKS Clusters",
        "table": "Resources",
        "query": (
            "Resources | where type =~ 'microsoft.containerservice/managedclusters' "
            "| project subscriptionId, resourceGroup, name, location, "
            "kubernetesVersion=tostring(properties.kubernetesVersion), "
            "currentKubernetesVersion=tostring(properties.currentKubernetesVersion), "
            "dnsPrefix=tostring(properties.dnsPrefix), "
            "fqdn=tostring(properties.fqdn), "
            "nodeResourceGroup=tostring(properties.nodeResourceGroup), "
            "enableRBAC=tobool(properties.enableRBAC), "
            "networkPlugin=tostring(properties.networkProfile.networkPlugin), "
            "networkPolicy=tostring(properties.networkProfile.networkPolicy), "
            "serviceCidr=tostring(properties.networkProfile.serviceCidr), "
            "authorizedIpCount=array_length(properties.apiServerAccessProfile.authorizedIPRanges), "
            "privateCluster=tobool(properties.apiServerAccessProfile.enablePrivateCluster), "
            "nodePoolCount=array_length(properties.agentPoolProfiles), "
            "powerState=tostring(properties.powerState.code), "
            "provisioningState=tostring(properties.provisioningState), "
            "identityType=tostring(identity.type), "
            "tags=tostring(tags), id"
        ),
    },
    {
        "sheet": "App Services",
        "table": "Resources",
        "query": (
            "Resources | where type =~ 'microsoft.web/sites' "
            "| project subscriptionId, resourceGroup, name, location, "
            "kind, "
            "state=tostring(properties.state), "
            "enabled=tobool(properties.enabled), "
            "httpsOnly=tobool(properties.httpsOnly), "
            "clientCertEnabled=tobool(properties.clientCertEnabled), "
            "publicNetworkAccess=tostring(properties.publicNetworkAccess), "
            "serverFarmId=tostring(properties.serverFarmId), "
            "defaultHostName=tostring(properties.defaultHostName), "
            "minTlsVersion=tostring(properties.siteConfig.minTlsVersion), "
            "ftpsState=tostring(properties.siteConfig.ftpsState), "
            "linuxFxVersion=tostring(properties.siteConfig.linuxFxVersion), "
            "netFrameworkVersion=tostring(properties.siteConfig.netFrameworkVersion), "
            "pythonVersion=tostring(properties.siteConfig.pythonVersion), "
            "nodeVersion=tostring(properties.siteConfig.nodeVersion), "
            "identityType=tostring(identity.type), "
            "tags=tostring(tags), id"
        ),
    },
    {
        "sheet": "Network Interfaces",
        "table": "Resources",
        "query": (
            "Resources | where type =~ 'microsoft.network/networkinterfaces' "
            "| extend ipConfig = properties.ipConfigurations[0].properties "
            "| project subscriptionId, resourceGroup, name, location, "
            "privateIp=tostring(ipConfig.privateIPAddress), "
            "privateIpAllocation=tostring(ipConfig.privateIPAllocationMethod), "
            "subnetId=tostring(ipConfig.subnet.id), "
            "publicIpId=tostring(ipConfig.publicIPAddress.id), "
            "nsgId=tostring(properties.networkSecurityGroup.id), "
            "macAddress=tostring(properties.macAddress), "
            "enableAcceleratedNetworking=tobool(properties.enableAcceleratedNetworking), "
            "enableIPForwarding=tobool(properties.enableIPForwarding), "
            "vmId=tostring(properties.virtualMachine.id), "
            "tags=tostring(tags), id"
        ),
    },
    {
        "sheet": "Public IPs",
        "table": "Resources",
        "query": (
            "Resources | where type =~ 'microsoft.network/publicipaddresses' "
            "| project subscriptionId, resourceGroup, name, location, "
            "skuName=tostring(sku.name), skuTier=tostring(sku.tier), "
            "ipAddress=tostring(properties.ipAddress), "
            "allocationMethod=tostring(properties.publicIPAllocationMethod), "
            "addressVersion=tostring(properties.publicIPAddressVersion), "
            "associatedTo=tostring(properties.ipConfiguration.id), "
            "fqdn=tostring(properties.dnsSettings.fqdn), "
            "idleTimeoutInMinutes=toint(properties.idleTimeoutInMinutes), "
            "tags=tostring(tags), id"
        ),
    },
    {
        "sheet": "Network Security Groups",
        "table": "Resources",
        "query": (
            "Resources | where type =~ 'microsoft.network/networksecuritygroups' "
            "| project subscriptionId, resourceGroup, name, location, "
            "customRuleCount=array_length(properties.securityRules), "
            "defaultRuleCount=array_length(properties.defaultSecurityRules), "
            "associatedSubnetCount=array_length(properties.subnets), "
            "associatedNicCount=array_length(properties.networkInterfaces), "
            "flowLogCount=array_length(properties.flowLogs), "
            "tags=tostring(tags), id"
        ),
    },
    {
        "sheet": "Load Balancers",
        "table": "Resources",
        "query": (
            "Resources | where type =~ 'microsoft.network/loadbalancers' "
            "| project subscriptionId, resourceGroup, name, location, "
            "skuName=tostring(sku.name), skuTier=tostring(sku.tier), "
            "frontendIpCount=array_length(properties.frontendIPConfigurations), "
            "backendPoolCount=array_length(properties.backendAddressPools), "
            "loadBalancingRuleCount=array_length(properties.loadBalancingRules), "
            "inboundNatRuleCount=array_length(properties.inboundNatRules), "
            "outboundRuleCount=array_length(properties.outboundRules), "
            "probeCount=array_length(properties.probes), "
            "tags=tostring(tags), id"
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
        "sheet": "Cosmos DB Accounts",
        "table": "Resources",
        "query": (
            "Resources | where type =~ 'microsoft.documentdb/databaseaccounts' "
            "| project subscriptionId, resourceGroup, name, location, "
            "kind, "
            "offerType=tostring(properties.databaseAccountOfferType), "
            "consistencyLevel=tostring(properties.consistencyPolicy.defaultConsistencyLevel), "
            "enableAutomaticFailover=tobool(properties.enableAutomaticFailover), "
            "enableMultipleWriteLocations=tobool(properties.enableMultipleWriteLocations), "
            "isVirtualNetworkFilterEnabled=tobool(properties.isVirtualNetworkFilterEnabled), "
            "publicNetworkAccess=tostring(properties.publicNetworkAccess), "
            "minimalTlsVersion=tostring(properties.minimalTlsVersion), "
            "disableLocalAuth=tobool(properties.disableLocalAuth), "
            "locationCount=array_length(properties.locations), "
            "capabilities=tostring(properties.capabilities), "
            "tags=tostring(tags), id"
        ),
    },
    {
        "sheet": "Storage Accounts",
        "table": "Resources",
        "query": (
            "Resources | where type =~ 'microsoft.storage/storageaccounts' "
            "| project subscriptionId, resourceGroup, name, location, "
            "kind, skuName=tostring(sku.name), skuTier=tostring(sku.tier), "
            "accessTier=tostring(properties.accessTier), "
            "minimumTlsVersion=tostring(properties.minimumTlsVersion), "
            "supportsHttpsTrafficOnly=tobool(properties.supportsHttpsTrafficOnly), "
            "allowBlobPublicAccess=tobool(properties.allowBlobPublicAccess), "
            "allowSharedKeyAccess=tobool(properties.allowSharedKeyAccess), "
            "publicNetworkAccess=tostring(properties.publicNetworkAccess), "
            "networkDefaultAction=tostring(properties.networkAcls.defaultAction), "
            "networkBypass=tostring(properties.networkAcls.bypass), "
            "isHnsEnabled=tobool(properties.isHnsEnabled), "
            "encryptionKeySource=tostring(properties.encryption.keySource), "
            "requireInfrastructureEncryption=tobool(properties.encryption.requireInfrastructureEncryption), "
            "primaryLocation=tostring(properties.primaryLocation), "
            "statusOfPrimary=tostring(properties.statusOfPrimary), "
            "tags=tostring(tags), id"
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
        "sheet": "Key Vaults",
        "table": "Resources",
        "query": (
            "Resources | where type =~ 'microsoft.keyvault/vaults' "
            "| project subscriptionId, resourceGroup, name, location, "
            "skuFamily=tostring(properties.sku.family), "
            "skuName=tostring(properties.sku.name), "
            "enabledForDeployment=tobool(properties.enabledForDeployment), "
            "enabledForDiskEncryption=tobool(properties.enabledForDiskEncryption), "
            "enabledForTemplateDeployment=tobool(properties.enabledForTemplateDeployment), "
            "enableRbacAuthorization=tobool(properties.enableRbacAuthorization), "
            "enableSoftDelete=tobool(properties.enableSoftDelete), "
            "softDeleteRetentionInDays=toint(properties.softDeleteRetentionInDays), "
            "enablePurgeProtection=tobool(properties.enablePurgeProtection), "
            "publicNetworkAccess=tostring(properties.publicNetworkAccess), "
            "networkDefaultAction=tostring(properties.networkAcls.defaultAction), "
            "accessPolicyCount=array_length(properties.accessPolicies), "
            "tags=tostring(tags), id"
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
    {
        "sheet": "Maintenance",
        "table": "MaintenanceResources",
        "query": (
            "MaintenanceResources "
            "| project subscriptionId, resourceGroup, type, name, location, id"
        ),
    },
    {
        "sheet": "Patch Assessment",
        "table": "PatchAssessmentResources",
        "query": (
            "PatchAssessmentResources "
            "| project subscriptionId, resourceGroup, type, name, location, id"
        ),
    },
]

# Resource types we project into a dedicated sheet beyond "All Resources".
# Used by the Coverage Audit sheet to flag types that only land in "All Resources".
DEDICATED_TYPES = {
    "microsoft.compute/virtualmachines",
    "microsoft.compute/disks",
    "microsoft.containerservice/managedclusters",
    "microsoft.web/sites",
    "microsoft.network/networkinterfaces",
    "microsoft.network/publicipaddresses",
    "microsoft.network/networksecuritygroups",
    "microsoft.network/loadbalancers",
    "microsoft.network/virtualnetworks",
    "microsoft.sql/servers/databases",
    "microsoft.documentdb/databaseaccounts",
    "microsoft.storage/storageaccounts",
    "microsoft.storage/storageaccounts/blobservices/containers",
    "microsoft.keyvault/vaults",
    "microsoft.authorization/locks",
}


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


def _build_coverage_audit(all_resources_df, pd) -> "pd.DataFrame":
    """
    Build the Coverage Audit sheet from the All Resources frame.

    For every resource type present in the tenant, report row count and
    whether resource_graph_export expands it into a dedicated sheet. Types
    not in DEDICATED_TYPES land only in "All Resources" — those rows tell
    you where to add coverage next.
    """
    if all_resources_df is None or all_resources_df.empty or "type" not in all_resources_df.columns:
        return pd.DataFrame(columns=["type", "count", "has_dedicated_sheet"])

    counts = (
        all_resources_df["type"].astype(str).str.lower().value_counts().reset_index()
    )
    counts.columns = ["type", "count"]
    counts["has_dedicated_sheet"] = counts["type"].isin(DEDICATED_TYPES).map(
        {True: "Yes", False: "No"}
    )
    return counts


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

    audit_df = _build_coverage_audit(sheets.get("All Resources"), pd)

    sheets = {
        "Snapshot": snapshot_metadata(config, detect_cloud(), sub_count=len(sub_ids)),
        "Summary": pd.DataFrame(summary_rows),
        **sheets,
        "Coverage Audit": audit_df,
    }

    filename = make_filename(resolve_scope_label(config, sub_ids), "resource-graph", "all")
    path = save_dataframes(sheets, filename)
    if path:
        print(f"\nWrote: {path}")
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
