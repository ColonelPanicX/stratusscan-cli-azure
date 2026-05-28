#!/usr/bin/env python3
"""StratusScanCLI-Azure — Firewall Policy Rules Export"""

import sys
from pathlib import Path

try:
    import utils
except ImportError:
    sys.path.append(str(Path(__file__).parent.parent.parent))
    import utils

import pandas as pd

utils.setup_logging("firewall-policy-rules-export")
utils.log_script_start("firewall_policy_rules_export.py", "Azure Firewall Policy Rules Export")

log = utils.get_logger()


def _join(items) -> str:
    if not items:
        return ""
    return ", ".join(str(i) for i in items)


def _rule_type_label(rule) -> str:
    rt = getattr(rule, "rule_type", "") or ""
    return rt.replace("Rule", "").strip() or rt


def _extract_network_rule(rule, base: dict) -> dict:
    row = dict(base)
    row["Rule Name"] = rule.name or ""
    row["Rule Type"] = "Network"
    row["Protocols"] = _join(rule.ip_protocols)
    row["Source Addresses"] = _join(rule.source_addresses)
    row["Source IP Groups"] = _join(rule.source_ip_groups)
    row["Destination Addresses"] = _join(rule.destination_addresses)
    row["Destination IP Groups"] = _join(rule.destination_ip_groups)
    row["Destination FQDNs"] = _join(rule.destination_fqdns)
    row["Destination Ports"] = _join(rule.destination_ports)
    row["Target FQDNs"] = ""
    row["Target URLs"] = ""
    row["Translated Address"] = ""
    row["Translated Port"] = ""
    return row


def _extract_application_rule(rule, base: dict) -> dict:
    row = dict(base)
    row["Rule Name"] = rule.name or ""
    row["Rule Type"] = "Application"
    protocols = []
    for p in (rule.protocols or []):
        port = getattr(p, "port", "")
        ptype = getattr(p, "protocol_type", "")
        protocols.append(f"{ptype}:{port}" if port else str(ptype))
    row["Protocols"] = ", ".join(protocols)
    row["Source Addresses"] = _join(rule.source_addresses)
    row["Source IP Groups"] = _join(rule.source_ip_groups)
    row["Destination Addresses"] = ""
    row["Destination IP Groups"] = ""
    row["Destination FQDNs"] = _join(getattr(rule, "fqdn_tags", None))
    row["Destination Ports"] = ""
    row["Target FQDNs"] = _join(rule.target_fqdns)
    row["Target URLs"] = _join(getattr(rule, "target_urls", None))
    row["Translated Address"] = ""
    row["Translated Port"] = ""
    return row


def _extract_nat_rule(rule, base: dict) -> dict:
    row = dict(base)
    row["Rule Name"] = rule.name or ""
    row["Rule Type"] = "DNAT"
    row["Protocols"] = _join(rule.ip_protocols)
    row["Source Addresses"] = _join(rule.source_addresses)
    row["Source IP Groups"] = _join(rule.source_ip_groups)
    row["Destination Addresses"] = _join(rule.destination_addresses)
    row["Destination IP Groups"] = ""
    row["Destination FQDNs"] = ""
    row["Destination Ports"] = _join(rule.destination_ports)
    row["Target FQDNs"] = ""
    row["Target URLs"] = ""
    row["Translated Address"] = getattr(rule, "translated_address", "") or ""
    row["Translated Port"] = str(getattr(rule, "translated_port", "") or "")
    return row


RULE_EXTRACTORS = {
    "NetworkRule": _extract_network_rule,
    "ApplicationRule": _extract_application_rule,
    "NatRule": _extract_nat_rule,
}


def collect_policies(subscription_id: str) -> list:
    client = utils.get_azure_client("network", subscription_id)
    log.info("Listing all firewall policies in subscription %s", subscription_id)
    return list(client.firewall_policies.list_all())


def collect_rule_collection_groups(subscription_id: str, resource_group: str, policy_name: str) -> list:
    client = utils.get_azure_client("network", subscription_id)
    log.info("Listing rule collection groups for policy %s", policy_name)
    return list(client.firewall_policy_rule_collection_groups.list(resource_group, policy_name))


def main(subscription_id: str, subscription_name: str) -> None:
    environment = utils.detect_environment()
    if not utils.is_service_available_in_environment("network", environment):
        sys.exit(0)

    policies = collect_policies(subscription_id)
    if not policies:
        print("No firewall policies found.")
        return

    rows = []
    for policy in policies:
        policy_rg = utils.extract_resource_group(policy.id)
        policy_name = policy.name or ""

        try:
            rcgs = collect_rule_collection_groups(subscription_id, policy_rg, policy_name)
        except Exception as e:
            log.warning("Failed to list rule collection groups for %s: %s", policy_name, e)
            continue

        for rcg in rcgs:
            rcg_name = rcg.name or ""
            rcg_priority = rcg.priority or ""

            for rc in (rcg.rule_collections or []):
                rc_name = rc.name or ""
                rc_priority = getattr(rc, "priority", "") or ""
                action = ""
                if hasattr(rc, "action") and rc.action:
                    action = getattr(rc.action, "type", "") or ""

                base = {
                    "Policy Name": policy_name,
                    "Policy Resource Group": policy_rg,
                    "Rule Collection Group": rcg_name,
                    "RCG Priority": rcg_priority,
                    "Rule Collection": rc_name,
                    "RC Priority": rc_priority,
                    "Action": action,
                }

                for rule in (rc.rules or []):
                    rule_type = getattr(rule, "rule_type", "") or ""
                    extractor = RULE_EXTRACTORS.get(rule_type)
                    if extractor:
                        rows.append(extractor(rule, base))
                    else:
                        row = dict(base)
                        row["Rule Name"] = getattr(rule, "name", "") or ""
                        row["Rule Type"] = rule_type
                        rows.append(row)

    if not rows:
        print("No firewall policy rules found.")
        return

    df = pd.DataFrame(rows)
    filename = utils.create_export_filename(subscription_name, "firewall-policy-rules", "all")
    utils.save_dataframe_to_excel(df, filename, sheet_name="Firewall Policy Rules")
    print(f"Exported {len(rows)} firewall policy rule(s) → {filename}")
    log.info("Export complete: %d rules across %d policies", len(rows), len(policies))


if __name__ == "__main__":
    sub_id, sub_name = utils.resolve_target_subscription()
    if not sub_id:
        print("ERROR: No subscription configured. Run configure.py first.")
        sys.exit(1)
    main(sub_id, sub_name)
