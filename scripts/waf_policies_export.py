#!/usr/bin/env python3
"""StratusScanCLI-Azure — Web Application Firewall Policies Export

Covers the Application Gateway WAF family
(Microsoft.Network/ApplicationGatewayWebApplicationFirewallPolicies), listed
subscription-wide by network.web_application_firewall_policies.list_all().

Not covered: the Front Door WAF family
(Microsoft.Network/FrontDoorWebApplicationFirewallPolicies). It is a separate
resource type served by a separate operation group that azure-mgmt-network 32
does not carry — it lives in azure-mgmt-frontdoor, which this project does not
depend on. Front Door WAF policies therefore do not appear in this workbook.

The "Policy Type" column names the family so the scope of the export is visible
in the evidence itself. There is no SKU column: sku is a Front Door WAF
property, and Application Gateway WAF policies do not carry one.

Two sheets: Policies (one row per policy, with the managed rule sets joined)
and Custom Rules (one row per custom rule, with its match conditions
summarized).
"""

import sys
from pathlib import Path
from typing import Any

try:
    import utils
except ImportError:
    sys.path.append(str(Path(__file__).parent.parent))
    import utils

import pandas as pd

log = utils.get_logger()

POLICY_TYPE = "Application Gateway"

POLICY_COLUMNS = [
    "Name", "Resource Group", "Location", "Policy Type", "Mode", "State",
    "Request Body Check", "Max Request Body Size (KB)", "File Upload Limit (MB)",
    "Managed Rule Sets", "Managed Rule Set Count", "Custom Rule Count",
    "Associated Application Gateways", "Associated Listeners",
    "Associated Path-Based Rules", "Resource State", "Provisioning State", "Tags",
]
CUSTOM_RULE_COLUMNS = [
    "Policy", "Resource Group", "Rule Name", "Priority", "Rule Type", "Action",
    "State", "Match Conditions", "Rate Limit Threshold", "Rate Limit Duration",
]


def collect_policies(client) -> list:
    log.info("Listing web application firewall policies")
    return list(client.web_application_firewall_policies.list_all())


def _names(resources) -> str:
    names = []
    for resource in resources or []:
        name = utils.s(getattr(resource, "name", None))
        if not name:
            name = utils.s(getattr(resource, "id", None)).rstrip("/").split("/")[-1]
        if name:
            names.append(name)
    return ", ".join(names)


def _managed_rule_sets(policy) -> list:
    managed = getattr(policy, "managed_rules", None)
    return list(getattr(managed, "managed_rule_sets", None) or [])


def _rule_set_text(rule_sets) -> str:
    return ", ".join(
        f"{utils.s(getattr(rs, 'rule_set_type', None))} "
        f"{utils.s(getattr(rs, 'rule_set_version', None))}".strip()
        for rs in rule_sets
    )


def build_policy_row(policy) -> dict[str, Any]:
    settings = getattr(policy, "policy_settings", None)
    rule_sets = _managed_rule_sets(policy)
    tags = getattr(policy, "tags", None) or {}
    return {
        "Name": utils.s(getattr(policy, "name", None)),
        "Resource Group": utils.extract_resource_group(getattr(policy, "id", None)),
        "Location": utils.s(getattr(policy, "location", None)),
        "Policy Type": POLICY_TYPE,
        "Mode": utils.s(getattr(settings, "mode", None)),
        "State": utils.s(getattr(settings, "state", None)),
        "Request Body Check": "Yes" if getattr(settings, "request_body_check", False) else "No",
        "Max Request Body Size (KB)": utils.s(
            getattr(settings, "max_request_body_size_in_kb", None)
        ),
        "File Upload Limit (MB)": utils.s(getattr(settings, "file_upload_limit_in_mb", None)),
        "Managed Rule Sets": _rule_set_text(rule_sets),
        "Managed Rule Set Count": len(rule_sets),
        "Custom Rule Count": len(getattr(policy, "custom_rules", None) or []),
        "Associated Application Gateways": _names(getattr(policy, "application_gateways", None)),
        "Associated Listeners": _names(getattr(policy, "http_listeners", None)),
        "Associated Path-Based Rules": _names(getattr(policy, "path_based_rules", None)),
        "Resource State": utils.s(getattr(policy, "resource_state", None)),
        "Provisioning State": utils.s(getattr(policy, "provisioning_state", None)),
        "Tags": "; ".join(f"{k}={v}" for k, v in tags.items()),
    }


def _match_condition_text(condition) -> str:
    variables = []
    for variable in getattr(condition, "match_variables", None) or []:
        name = utils.s(getattr(variable, "variable_name", None))
        selector = utils.s(getattr(variable, "selector", None))
        variables.append(f"{name}[{selector}]" if selector else name)
    operator = utils.s(getattr(condition, "operator", None))
    if getattr(condition, "negation_conditon", False):
        operator = f"NOT {operator}".strip()
    values = ", ".join(utils.s(v) for v in (getattr(condition, "match_values", None) or []))
    transforms = ", ".join(utils.s(t) for t in (getattr(condition, "transforms", None) or []))
    text = f"{'+'.join(variables)} {operator} [{values}]".strip()
    return f"{text} (transforms: {transforms})" if transforms else text


def build_custom_rule_rows(policy) -> list[dict[str, Any]]:
    policy_name = utils.s(getattr(policy, "name", None))
    resource_group = utils.extract_resource_group(getattr(policy, "id", None))
    rows = []
    for rule in getattr(policy, "custom_rules", None) or []:
        conditions = getattr(rule, "match_conditions", None) or []
        rows.append({
            "Policy": policy_name,
            "Resource Group": resource_group,
            "Rule Name": utils.s(getattr(rule, "name", None)),
            "Priority": utils.s(getattr(rule, "priority", None)),
            "Rule Type": utils.s(getattr(rule, "rule_type", None)),
            "Action": utils.s(getattr(rule, "action", None)),
            "State": utils.s(getattr(rule, "state", None)),
            "Match Conditions": " AND ".join(
                _match_condition_text(condition) for condition in conditions
            ),
            "Rate Limit Threshold": utils.s(getattr(rule, "rate_limit_threshold", None)),
            "Rate Limit Duration": utils.s(getattr(rule, "rate_limit_duration", None)),
        })
    return rows


def main(subscription_id: str, subscription_name: str) -> utils.ExportResult:
    environment = utils.detect_environment()
    if not utils.is_service_available_in_environment("network", environment):
        sys.exit(0)

    client = utils.get_azure_client("network", subscription_id)
    policies = collect_policies(client)
    if not policies:
        raise utils.NoResourcesFound("web application firewall policies")

    policy_rows = [build_policy_row(policy) for policy in policies]
    custom_rule_rows = [row for policy in policies for row in build_custom_rule_rows(policy)]

    sheets = {
        "Policies": pd.DataFrame(policy_rows, columns=POLICY_COLUMNS),
        "Custom Rules": pd.DataFrame(custom_rule_rows, columns=CUSTOM_RULE_COLUMNS),
    }
    filename = utils.create_export_filename(subscription_name, "waf-policies", "all")
    utils.save_multiple_dataframes_to_excel(sheets, filename)

    detection = sum(1 for row in policy_rows if row["Mode"].lower() == "detection")
    print(
        f"Exported {len(policy_rows)} WAF policy(ies) and {len(custom_rule_rows)} custom rule(s); "
        f"{detection} in Detection mode → {filename}"
    )
    log.info(
        "Export complete: %d WAF policies, %d custom rules, %d in Detection mode",
        len(policy_rows), len(custom_rule_rows), detection,
    )
    return utils.ExportResult(rows=len(policy_rows), filename=filename, errors=[])


if __name__ == "__main__":
    import runner

    runner.run_exporter(main, "waf-policies")
