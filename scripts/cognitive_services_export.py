#!/usr/bin/env python3
"""StratusScanCLI-Azure — Azure AI / Cognitive Services Accounts Export

One subscription-wide listing (accounts.list()) covering every kind of Azure AI
Services account, including Azure OpenAI (kind "OpenAI").

Keys are never read. The accounts operation group has an operation that
returns live account keys; this exporter does not call it, and no column in
this workbook can carry key material. Local (key-based) authentication is
reported through the Disable Local Auth column, which is the control-plane
setting, not a secret.

Model deployments are not exported: deployments.list() is scoped to a single
account (resource group + account name), so covering them would be one call per
account. That is a deliberate omission, not an oversight.
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

COLUMNS = [
    "Name", "Resource Group", "Location", "Kind", "SKU", "SKU Tier", "Endpoint",
    "Public Network Access", "Disable Local Auth", "Custom Subdomain",
    "Network ACL Default Action", "Network ACL Bypass", "IP Rule Count",
    "VNet Rule Count", "Private Endpoint Count", "Encryption Key Source",
    "Encryption Key Vault URI", "Encryption Key Name", "Identity Type",
    "Identity Principal ID", "Restrict Outbound Network Access",
    "Allowed FQDN Count", "Provisioning State", "Tags",
]


def collect_accounts(subscription_id: str) -> list:
    client = utils.get_azure_client("cognitiveservices", subscription_id)
    log.info("Listing Cognitive Services accounts in subscription %s", subscription_id)
    return list(client.accounts.list())


def _yes_no(value: Any) -> str:
    if value is None:
        return ""
    return "Yes" if value else "No"


def build_row(account) -> dict[str, Any]:
    props = getattr(account, "properties", None)
    sku = getattr(account, "sku", None)
    identity = getattr(account, "identity", None)
    network_acls = getattr(props, "network_acls", None)
    encryption = getattr(props, "encryption", None)
    key_vault = getattr(encryption, "key_vault_properties", None)
    tags = getattr(account, "tags", None) or {}

    return {
        "Name": utils.s(getattr(account, "name", None)),
        "Resource Group": utils.extract_resource_group(getattr(account, "id", None)),
        "Location": utils.s(getattr(account, "location", None)),
        "Kind": utils.s(getattr(account, "kind", None)),
        "SKU": utils.s(getattr(sku, "name", None)),
        "SKU Tier": utils.s(getattr(sku, "tier", None)),
        "Endpoint": utils.s(getattr(props, "endpoint", None)),
        "Public Network Access": utils.s(getattr(props, "public_network_access", None)),
        "Disable Local Auth": _yes_no(getattr(props, "disable_local_auth", None)),
        "Custom Subdomain": utils.s(getattr(props, "custom_sub_domain_name", None)),
        "Network ACL Default Action": utils.s(getattr(network_acls, "default_action", None)),
        "Network ACL Bypass": utils.s(getattr(network_acls, "bypass", None)),
        "IP Rule Count": len(getattr(network_acls, "ip_rules", None) or []),
        "VNet Rule Count": len(getattr(network_acls, "virtual_network_rules", None) or []),
        "Private Endpoint Count": len(getattr(props, "private_endpoint_connections", None) or []),
        "Encryption Key Source": utils.s(getattr(encryption, "key_source", None)),
        "Encryption Key Vault URI": utils.s(getattr(key_vault, "key_vault_uri", None)),
        "Encryption Key Name": utils.s(getattr(key_vault, "key_name", None)),
        "Identity Type": utils.s(getattr(identity, "type", None)),
        "Identity Principal ID": utils.s(getattr(identity, "principal_id", None)),
        "Restrict Outbound Network Access": _yes_no(
            getattr(props, "restrict_outbound_network_access", None)
        ),
        "Allowed FQDN Count": len(getattr(props, "allowed_fqdn_list", None) or []),
        "Provisioning State": utils.s(getattr(props, "provisioning_state", None)),
        "Tags": "; ".join(f"{k}={v}" for k, v in tags.items()),
    }


def main(subscription_id: str, subscription_name: str) -> utils.ExportResult:
    environment = utils.detect_environment()
    if not utils.is_service_available_in_environment("cognitiveservices", environment):
        sys.exit(0)

    accounts = collect_accounts(subscription_id)
    if not accounts:
        raise utils.NoResourcesFound("Cognitive Services accounts")

    rows = [build_row(account) for account in accounts]
    df = pd.DataFrame(rows, columns=COLUMNS)
    filename = utils.create_export_filename(subscription_name, "cognitive-services", "all")
    utils.save_dataframe_to_excel(df, filename, sheet_name="AI Services Accounts")

    openai = sum(1 for row in rows if row["Kind"].lower() == "openai")
    print(
        f"Exported {len(rows)} AI Services account(s), {openai} of kind OpenAI → {filename}"
    )
    log.info("Export complete: %d accounts, %d OpenAI", len(rows), openai)
    return utils.ExportResult(rows=len(rows), filename=filename, errors=[])


if __name__ == "__main__":
    import runner

    runner.run_exporter(main, "cognitive-services")
