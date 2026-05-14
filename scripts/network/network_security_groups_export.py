#!/usr/bin/env python3
"""StratusScanCLI-Azure — Network Security Groups Export"""

import os
import sys
from pathlib import Path

try:
    import utils
except ImportError:
    sys.path.append(str(Path(__file__).parent.parent.parent))
    import utils

import pandas as pd
from azure.mgmt.resourcegraph.models import QueryRequest, QueryRequestOptions

utils.setup_logging("nsg-export")
utils.log_script_start("network_security_groups_export.py", "Azure NSG Export")

log = utils.get_logger()

NSG_SUMMARY_COLUMNS = [
    "Name",
    "Resource Group",
    "Location",
    "Custom Rule Count",
    "Default Rule Count",
    "Associated Subnets",
    "Associated NICs",
    "Flow Log Count",
    "Provisioning State",
    "ID",
    "Tags",
]

NSG_RULE_COLUMNS = [
    "Subscription ID",
    "Resource Group",
    "NSG Name",
    "Location",
    "Rule Type",
    "Rule Name",
    "Priority",
    "Direction",
    "Access",
    "Protocol",
    "Source Address Prefix",
    "Source Address Prefixes",
    "Source Port Range",
    "Source Port Ranges",
    "Destination Address Prefix",
    "Destination Address Prefixes",
    "Destination Port Range",
    "Destination Port Ranges",
    "Description",
    "Source Application Security Groups",
    "Destination Application Security Groups",
    "ID",
]

NSG_SUMMARY_QUERY = """
Resources
| where type =~ 'microsoft.network/networksecuritygroups'
| project
    name,
    resourceGroup,
    location,
    customRuleCount=array_length(properties.securityRules),
    defaultRuleCount=array_length(properties.defaultSecurityRules),
    associatedSubnetCount=array_length(properties.subnets),
    associatedNicCount=array_length(properties.networkInterfaces),
    flowLogCount=array_length(properties.flowLogs),
    provisioningState=tostring(properties.provisioningState),
    id,
    tags=tostring(tags)
"""

NSG_RULES_QUERY = """
Resources
| where type =~ 'microsoft.network/networksecuritygroups'
| mv-expand rule = properties.securityRules
| extend ruleType = 'Custom'
| project
    subscriptionId,
    resourceGroup,
    nsgName=name,
    location,
    ruleType,
    ruleName=tostring(rule.name),
    priority=toint(rule.properties.priority),
    direction=tostring(rule.properties.direction),
    access=tostring(rule.properties.access),
    protocol=tostring(rule.properties.protocol),
    sourceAddressPrefix=tostring(rule.properties.sourceAddressPrefix),
    sourceAddressPrefixes=tostring(rule.properties.sourceAddressPrefixes),
    sourcePortRange=tostring(rule.properties.sourcePortRange),
    sourcePortRanges=tostring(rule.properties.sourcePortRanges),
    destinationAddressPrefix=tostring(rule.properties.destinationAddressPrefix),
    destinationAddressPrefixes=tostring(rule.properties.destinationAddressPrefixes),
    destinationPortRange=tostring(rule.properties.destinationPortRange),
    destinationPortRanges=tostring(rule.properties.destinationPortRanges),
    description=tostring(rule.properties.description),
    sourceAppSecGroups=tostring(rule.properties.sourceApplicationSecurityGroups),
    destinationAppSecGroups=tostring(rule.properties.destinationApplicationSecurityGroups),
    id=strcat(id, '/securityRules/', tostring(rule.name))
| union (
    Resources
    | where type =~ 'microsoft.network/networksecuritygroups'
    | mv-expand rule = properties.defaultSecurityRules
    | extend ruleType = 'Default'
    | project
        subscriptionId,
        resourceGroup,
        nsgName=name,
        location,
        ruleType,
        ruleName=tostring(rule.name),
        priority=toint(rule.properties.priority),
        direction=tostring(rule.properties.direction),
        access=tostring(rule.properties.access),
        protocol=tostring(rule.properties.protocol),
        sourceAddressPrefix=tostring(rule.properties.sourceAddressPrefix),
        sourceAddressPrefixes=tostring(rule.properties.sourceAddressPrefixes),
        sourcePortRange=tostring(rule.properties.sourcePortRange),
        sourcePortRanges=tostring(rule.properties.sourcePortRanges),
        destinationAddressPrefix=tostring(rule.properties.destinationAddressPrefix),
        destinationAddressPrefixes=tostring(rule.properties.destinationAddressPrefixes),
        destinationPortRange=tostring(rule.properties.destinationPortRange),
        destinationPortRanges=tostring(rule.properties.destinationPortRanges),
        description=tostring(rule.properties.description),
        sourceAppSecGroups=tostring(rule.properties.sourceApplicationSecurityGroups),
        destinationAppSecGroups=tostring(rule.properties.destinationApplicationSecurityGroups),
        id=strcat(id, '/securityRules/', tostring(rule.name))
)
| order by nsgName asc, ruleType asc, priority asc
"""


def _query_resource_graph(subscription_id: str, query: str) -> list:
    client = utils.get_azure_client("resourcegraph")
    rows = []
    skip_token = None

    while True:
        request = QueryRequest(
            subscriptions=[subscription_id],
            query=query,
            options=QueryRequestOptions(
                result_format="objectArray",
                skip_token=skip_token,
                top=1000,
            ),
        )
        response = client.resources(request)
        rows.extend(response.data or [])
        skip_token = response.skip_token
        if not skip_token:
            return rows


def _summary_dataframe(summary: list[dict]) -> pd.DataFrame:
    return pd.DataFrame(summary, columns=["Pull", "Rows", "Status", "Error"])


def collect_nsg_workbook(subscription_id: str) -> tuple[dict, int, int]:
    summary = []

    try:
        log.info("Querying NSG inventory via Resource Graph for %s", subscription_id)
        nsg_rows = _query_resource_graph(subscription_id, NSG_SUMMARY_QUERY)
        nsg_df = pd.DataFrame(
            [
                {
                    "Name": row.get("name", ""),
                    "Resource Group": row.get("resourceGroup", ""),
                    "Location": row.get("location", ""),
                    "Custom Rule Count": row.get("customRuleCount", 0),
                    "Default Rule Count": row.get("defaultRuleCount", 0),
                    "Associated Subnets": row.get("associatedSubnetCount", 0),
                    "Associated NICs": row.get("associatedNicCount", 0),
                    "Flow Log Count": row.get("flowLogCount", 0),
                    "Provisioning State": row.get("provisioningState", ""),
                    "ID": row.get("id", ""),
                    "Tags": row.get("tags", ""),
                }
                for row in nsg_rows
            ],
            columns=NSG_SUMMARY_COLUMNS,
        )
        summary.append(
            {"Pull": "Network Security Groups", "Rows": len(nsg_df), "Status": "OK", "Error": ""}
        )
    except Exception as exc:
        log.error("NSG inventory query failed: %s", exc)
        nsg_df = pd.DataFrame(columns=NSG_SUMMARY_COLUMNS)
        summary.append(
            {
                "Pull": "Network Security Groups",
                "Rows": 0,
                "Status": "ERROR",
                "Error": str(exc),
            }
        )

    try:
        log.info("Querying flattened NSG rules via Resource Graph for %s", subscription_id)
        rule_rows = _query_resource_graph(subscription_id, NSG_RULES_QUERY)
        rules_df = pd.DataFrame(
            [
                {
                    "Subscription ID": row.get("subscriptionId", ""),
                    "Resource Group": row.get("resourceGroup", ""),
                    "NSG Name": row.get("nsgName", ""),
                    "Location": row.get("location", ""),
                    "Rule Type": row.get("ruleType", ""),
                    "Rule Name": row.get("ruleName", ""),
                    "Priority": row.get("priority", ""),
                    "Direction": row.get("direction", ""),
                    "Access": row.get("access", ""),
                    "Protocol": row.get("protocol", ""),
                    "Source Address Prefix": row.get("sourceAddressPrefix", ""),
                    "Source Address Prefixes": row.get("sourceAddressPrefixes", ""),
                    "Source Port Range": row.get("sourcePortRange", ""),
                    "Source Port Ranges": row.get("sourcePortRanges", ""),
                    "Destination Address Prefix": row.get("destinationAddressPrefix", ""),
                    "Destination Address Prefixes": row.get("destinationAddressPrefixes", ""),
                    "Destination Port Range": row.get("destinationPortRange", ""),
                    "Destination Port Ranges": row.get("destinationPortRanges", ""),
                    "Description": row.get("description", ""),
                    "Source Application Security Groups": row.get("sourceAppSecGroups", ""),
                    "Destination Application Security Groups": row.get(
                        "destinationAppSecGroups", ""
                    ),
                    "ID": row.get("id", ""),
                }
                for row in rule_rows
            ],
            columns=NSG_RULE_COLUMNS,
        )
        summary.append({"Pull": "NSG Rules", "Rows": len(rules_df), "Status": "OK", "Error": ""})
    except Exception as exc:
        log.error("NSG rules query failed: %s", exc)
        rules_df = pd.DataFrame(columns=NSG_RULE_COLUMNS)
        summary.append({"Pull": "NSG Rules", "Rows": 0, "Status": "ERROR", "Error": str(exc)})

    sheets = {
        "Summary": _summary_dataframe(summary),
        "Network Security Groups": nsg_df,
        "NSG Rules": rules_df,
    }
    error_count = sum(1 for row in summary if row["Status"] == "ERROR")
    return sheets, len(nsg_df), error_count


def main(subscription_id: str, subscription_name: str) -> int:
    environment = utils.detect_environment()
    if not utils.is_service_available_in_environment("network", environment):
        return 0

    sheets, nsg_count, error_count = collect_nsg_workbook(subscription_id)

    filename = utils.create_export_filename(subscription_name, "network-security-groups", "all")
    utils.save_multiple_dataframes_to_excel(sheets, filename)
    if error_count:
        print(f"Exported NSG workbook with {error_count} error(s) -> {filename}")
        return 1

    print(f"Exported {nsg_count} network security group(s) -> {filename}")
    log.info("Export complete: %d NSGs", nsg_count)
    return 0


if __name__ == "__main__":
    cfg = utils.get_config()
    sub_id = os.environ.get("AZURESCAN_SUBSCRIPTION_ID", "") or cfg.get(
        "default_subscription_id", ""
    )
    sub_name = utils.get_subscription_name(sub_id)
    if not sub_id:
        print("ERROR: No subscription configured. Run configure.py first.")
        sys.exit(1)
    sys.exit(main(sub_id, sub_name))
