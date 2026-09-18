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

log = utils.get_logger()

_ANY_SOURCES = {"*", "0.0.0.0/0", "::/0", "internet"}
_MGMT_PORTS = (22, 3389)
_PORTLESS_PROTOCOLS = {"icmp", "esp", "ah"}


def collect_nsgs(subscription_id: str) -> list:
    client = utils.get_azure_client("network", subscription_id)
    log.info("Listing all NSGs in subscription %s", subscription_id)
    return list(client.network_security_groups.list_all())


def _join(items) -> str:
    if not items:
        return ""
    return ", ".join(utils.s(i) for i in items)


def _values(singular, plural) -> str:
    if plural:
        return _join(plural)
    return utils.s(singular)


def _asg_names(groups) -> str:
    return ", ".join(g.id.split("/")[-1] for g in (groups or []) if g.id)


def _port_ranges(singular, plural) -> list:
    ranges = list(plural) if plural else ([singular] if singular else [])
    return [utils.s(r) for r in ranges]


def _port_in_ranges(port: int, ranges: list) -> bool:
    for item in ranges:
        item = item.strip()
        if item == "*":
            return True
        low, _, high = item.partition("-")
        try:
            if high:
                if int(low) <= port <= int(high):
                    return True
            elif int(low) == port:
                return True
        except ValueError:
            continue
    return False


def is_any_source_inbound_allow(rule) -> bool:
    if utils.s(rule.direction).lower() != "inbound" or utils.s(rule.access).lower() != "allow":
        return False
    sources = list(rule.source_address_prefixes or [])
    if rule.source_address_prefix:
        sources.append(rule.source_address_prefix)
    return any(utils.s(src).strip().lower() in _ANY_SOURCES for src in sources)


def exposes_mgmt_ports(rule) -> bool:
    if not is_any_source_inbound_allow(rule):
        return False
    if utils.s(rule.protocol).lower() in _PORTLESS_PROTOCOLS:
        return False
    ranges = _port_ranges(rule.destination_port_range, rule.destination_port_ranges)
    return any(_port_in_ranges(port, ranges) for port in _MGMT_PORTS)


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
                "Direction": utils.s(rule.direction),
                "Access": utils.s(rule.access),
                "Protocol": utils.s(rule.protocol),
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
                "Source ASGs": _asg_names(rule.source_application_security_groups),
                "Destination ASGs": _asg_names(rule.destination_application_security_groups),
                "Any-Source Inbound Allow": is_any_source_inbound_allow(rule),
                "Mgmt Ports Exposed": exposes_mgmt_ports(rule),
            })
    return rows


def main(subscription_id: str, subscription_name: str) -> utils.ExportResult:
    environment = utils.detect_environment()
    if not utils.is_service_available_in_environment("network", environment):
        sys.exit(0)

    nsgs = collect_nsgs(subscription_id)
    if not nsgs:
        raise utils.NoResourcesFound("network security groups")

    rows = []
    rule_rows = []
    for nsg in nsgs:
        rg = utils.extract_resource_group(nsg.id)
        tags = nsg.tags or {}
        custom_rules = nsg.security_rules or []
        all_rules = list(custom_rules) + list(nsg.default_security_rules or [])
        default_inbound = len(nsg.default_security_rules or [])
        inbound_rules = sum(
            1 for r in custom_rules
            if utils.s(r.direction).lower() == "inbound"
        )
        outbound_rules = sum(
            1 for r in custom_rules
            if utils.s(r.direction).lower() == "outbound"
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
            "Provisioning State": utils.s(nsg.provisioning_state),
            "Tags": "; ".join(f"{k}={v}" for k, v in tags.items()),
            "Any-Source Inbound Allow": any(is_any_source_inbound_allow(r) for r in all_rules),
            "Mgmt Ports Exposed": any(exposes_mgmt_ports(r) for r in all_rules),
            "Unattached": associated_subnets == 0 and associated_nics == 0,
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
    return utils.ExportResult(rows=len(rows) + len(rule_rows), filename=filename, errors=[])


if __name__ == "__main__":
    import runner

    runner.run_exporter(main, "network-security-groups")
