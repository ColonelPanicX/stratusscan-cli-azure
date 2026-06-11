#!/usr/bin/env python3
"""StratusScanCLI-Azure — Network Security Groups Export"""

import sys
from pathlib import Path

try:
    import utils
except ImportError:
    sys.path.append(str(Path(__file__).parent.parent))
    import utils

import pandas as pd

utils.setup_logging("nsg-export")
utils.log_script_start("network_security_groups_export.py", "Azure NSG Export")

log = utils.get_logger()


def collect_nsgs(subscription_id: str) -> list:
    client = utils.get_azure_client("network", subscription_id)
    log.info("Listing all NSGs in subscription %s", subscription_id)
    return list(client.network_security_groups.list_all())


def _join(items) -> str:
    if not items:
        return ""
    return ", ".join(str(i) for i in items)


def _values(singular, plural) -> str:
    if plural:
        return _join(plural)
    return str(singular) if singular else ""


def _flatten_rules(nsg) -> list:
    rg = utils.extract_resource_group(nsg.id)
    rule_groups = (
        ("Custom", nsg.security_rules or []),
        ("Default", nsg.default_security_rules or []),
    )
    rows = []
    for rule_type, rules in rule_groups:
        for rule in rules:
            rows.append({
                "NSG Name": nsg.name,
                "Resource Group": rg,
                "Location": nsg.location,
                "Rule Name": rule.name,
                "Rule Type": rule_type,
                "Priority": rule.priority,
                "Direction": str(rule.direction or ""),
                "Access": str(rule.access or ""),
                "Protocol": str(rule.protocol or ""),
                "Source Ports": _values(rule.source_port_range, rule.source_port_ranges),
                "Destination Ports": _values(
                    rule.destination_port_range, rule.destination_port_ranges
                ),
                "Source Addresses": _values(
                    rule.source_address_prefix, rule.source_address_prefixes
                ),
                "Destination Addresses": _values(
                    rule.destination_address_prefix, rule.destination_address_prefixes
                ),
                "Description": rule.description or "",
            })
    return rows


def main(subscription_id: str, subscription_name: str) -> None:
    environment = utils.detect_environment()
    if not utils.is_service_available_in_environment("network", environment):
        sys.exit(0)

    nsgs = collect_nsgs(subscription_id)
    if not nsgs:
        print("No network security groups found.")
        return

    rows = []
    rule_rows = []
    for nsg in nsgs:
        rg = utils.extract_resource_group(nsg.id)
        tags = nsg.tags or {}
        default_inbound = len(nsg.default_security_rules or [])
        inbound_rules = sum(
            1 for r in (nsg.security_rules or [])
            if r.direction and str(r.direction).lower() == "inbound"
        )
        outbound_rules = sum(
            1 for r in (nsg.security_rules or [])
            if r.direction and str(r.direction).lower() == "outbound"
        )
        associated_subnets = len(nsg.subnets or [])
        associated_nics = len(nsg.network_interfaces or [])
        rows.append({
            "Name": nsg.name,
            "Resource Group": rg,
            "Location": nsg.location,
            "Custom Inbound Rules": inbound_rules,
            "Custom Outbound Rules": outbound_rules,
            "Default Rules": default_inbound,
            "Associated Subnets": associated_subnets,
            "Associated NICs": associated_nics,
            "Provisioning State": nsg.provisioning_state or "",
            "Tags": "; ".join(f"{k}={v}" for k, v in tags.items()),
        })
        rule_rows.extend(_flatten_rules(nsg))

    summary_df = pd.DataFrame(rows)
    rules_df = pd.DataFrame(rule_rows)
    filename = utils.create_export_filename(subscription_name, "network-security-groups", "all")
    utils.save_multiple_dataframes_to_excel(
        {"NSGs": summary_df, "Rules": rules_df}, filename
    )
    print(f"Exported {len(rows)} NSG(s) and {len(rule_rows)} rule(s) → {filename}")
    log.info("Export complete: %d NSGs, %d flattened rules", len(rows), len(rule_rows))


if __name__ == "__main__":
    sub_id, sub_name = utils.resolve_target_subscription()
    if not sub_id:
        print("ERROR: No subscription configured. Run configure.py first.")
        sys.exit(1)
    main(sub_id, sub_name)
