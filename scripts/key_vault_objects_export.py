#!/usr/bin/env python3
"""StratusScanCLI-Azure — Key Vault Objects (Keys / Secrets / Certificates) Export

Data-plane inventory of the objects inside each Key Vault: names, enabled state,
and lifecycle dates (created / updated / expiry). Secret and key *values* are never
read — this is an inventory tool, not a secrets dump.

Unlike the management-plane exporters, this reads the Key Vault data plane, which
requires data-plane permissions (RBAC roles such as Key Vault Reader / Crypto User /
Secrets User, or vault access policies with list permissions) that the read-only
management role does NOT grant. Vaults the caller cannot read are skipped with a
logged warning rather than failing the run.
"""

import datetime
import sys
from pathlib import Path

try:
    import utils
except ImportError:
    sys.path.append(str(Path(__file__).parent.parent))
    import utils

import pandas as pd
from azure.keyvault.certificates import CertificateClient
from azure.keyvault.keys import KeyClient
from azure.keyvault.secrets import SecretClient

utils.setup_logging("key-vault-objects-export")
utils.log_script_start("key_vault_objects_export.py", "Azure Key Vault Objects Export")

log = utils.get_logger()


def _fmt_date(value) -> str:
    return value.strftime("%m.%d.%Y") if value else ""


def _days_until(expires) -> object:
    if not expires:
        return ""
    now = datetime.datetime.now(datetime.timezone.utc)
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=datetime.timezone.utc)
    return (expires - now).days


def collect_vault_uris(subscription_id: str) -> list:
    client = utils.get_azure_client("keyvault", subscription_id)
    log.info("Listing all key vaults in subscription %s", subscription_id)
    uris = []
    for vault_ref in client.vaults.list():
        rg = utils.extract_resource_group(vault_ref.id)
        try:
            vault = client.vaults.get(rg, vault_ref.name)
        except Exception as exc:
            log.warning("Could not get vault detail for %s: %s", vault_ref.name, exc)
            continue
        uri = vault.properties.vault_uri if vault.properties else ""
        if uri:
            uris.append((vault_ref.name, uri))
    return uris


def _collect_keys(vault_name: str, uri: str, credential) -> list:
    rows = []
    try:
        client = KeyClient(vault_url=uri, credential=credential)
        for kp in client.list_properties_of_keys():
            rows.append({
                "Vault": vault_name,
                "Key Name": kp.name,
                "Enabled": kp.enabled,
                "Managed": kp.managed,
                "Created": _fmt_date(kp.created_on),
                "Updated": _fmt_date(kp.updated_on),
                "Not Before": _fmt_date(kp.not_before),
                "Expires": _fmt_date(kp.expires_on),
                "Days Until Expiry": _days_until(kp.expires_on),
                "Recovery Level": kp.recovery_level or "",
            })
    except Exception as exc:
        log.warning("Skipping keys for vault %s (no data-plane access?): %s", vault_name, exc)
    return rows


def _collect_secrets(vault_name: str, uri: str, credential) -> list:
    rows = []
    try:
        client = SecretClient(vault_url=uri, credential=credential)
        for sp in client.list_properties_of_secrets():
            rows.append({
                "Vault": vault_name,
                "Secret Name": sp.name,
                "Enabled": sp.enabled,
                "Managed": sp.managed,
                "Content Type": sp.content_type or "",
                "Created": _fmt_date(sp.created_on),
                "Updated": _fmt_date(sp.updated_on),
                "Not Before": _fmt_date(sp.not_before),
                "Expires": _fmt_date(sp.expires_on),
                "Days Until Expiry": _days_until(sp.expires_on),
            })
    except Exception as exc:
        log.warning("Skipping secrets for vault %s (no data-plane access?): %s", vault_name, exc)
    return rows


def _collect_certificates(vault_name: str, uri: str, credential) -> list:
    rows = []
    try:
        client = CertificateClient(vault_url=uri, credential=credential)
        for cp in client.list_properties_of_certificates():
            rows.append({
                "Vault": vault_name,
                "Certificate Name": cp.name,
                "Enabled": cp.enabled,
                "Created": _fmt_date(cp.created_on),
                "Updated": _fmt_date(cp.updated_on),
                "Not Before": _fmt_date(cp.not_before),
                "Expires": _fmt_date(cp.expires_on),
                "Days Until Expiry": _days_until(cp.expires_on),
            })
    except Exception as exc:
        log.warning(
            "Skipping certificates for vault %s (no data-plane access?): %s", vault_name, exc
        )
    return rows


def main(subscription_id: str, subscription_name: str) -> None:
    environment = utils.detect_environment()
    if not utils.is_service_available_in_environment("keyvault", environment):
        sys.exit(0)

    vault_uris = collect_vault_uris(subscription_id)
    if not vault_uris:
        print("No key vaults found.")
        return

    credential = utils.get_credential()
    key_rows, secret_rows, cert_rows = [], [], []
    for vault_name, uri in vault_uris:
        log.info("Reading data-plane objects for vault %s", vault_name)
        key_rows.extend(_collect_keys(vault_name, uri, credential))
        secret_rows.extend(_collect_secrets(vault_name, uri, credential))
        cert_rows.extend(_collect_certificates(vault_name, uri, credential))

    filename = utils.create_export_filename(subscription_name, "key-vault-objects", "all")
    utils.save_multiple_dataframes_to_excel(
        {
            "Keys": pd.DataFrame(key_rows),
            "Secrets": pd.DataFrame(secret_rows),
            "Certificates": pd.DataFrame(cert_rows),
        },
        filename,
    )
    print(
        f"Exported {len(key_rows)} key(s), {len(secret_rows)} secret(s), "
        f"{len(cert_rows)} certificate(s) across {len(vault_uris)} vault(s) → {filename}"
    )
    log.info(
        "Export complete: %d keys, %d secrets, %d certs",
        len(key_rows), len(secret_rows), len(cert_rows),
    )


if __name__ == "__main__":
    cfg = utils.get_config()
    sub_id = cfg.get("default_subscription_id", "")
    sub_name = utils.get_subscription_name(sub_id)
    if not sub_id:
        print("ERROR: No subscription configured. Run configure.py first.")
        sys.exit(1)
    main(sub_id, sub_name)
