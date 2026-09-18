#!/usr/bin/env python3
"""StratusScanCLI-Azure — Key Vault Objects (Keys / Secrets / Certificates) Export

Data-plane inventory of the objects inside each Key Vault: names, enabled state,
and lifecycle dates (created / updated / expiry). Secret and key *values* are never
read — this is an inventory tool, not a secrets dump.

Unlike the management-plane exporters, this reads the Key Vault data plane, which
requires data-plane permissions (RBAC roles such as Key Vault Reader / Crypto User /
Secrets User, or vault access policies with list permissions) that the read-only
management role does NOT grant, and a vault firewall that admits the caller's
address. A vault the caller cannot read is reported as unreadable on the
"Vault Access" sheet (ForbiddenByFirewall vs Forbidden/ForbiddenByRbac) and in the
Errors sheet — never as an empty vault.
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
from azure.core.exceptions import HttpResponseError
from azure.keyvault.certificates import CertificateClient
from azure.keyvault.keys import KeyClient
from azure.keyvault.secrets import SecretClient

utils.setup_logging("key-vault-objects-export")
utils.log_script_start("key_vault_objects_export.py", "Azure Key Vault Objects Export")

log = utils.get_logger()

ACCESS_OK = "OK"
ACCESS_COLUMNS = ["Vault", "Keys", "Secrets", "Certificates"]


def _fmt_date(value) -> str:
    return value.strftime("%m.%d.%Y") if value else ""


def _days_until(expires) -> object:
    if not expires:
        return ""
    now = datetime.datetime.now(datetime.timezone.utc)
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=datetime.timezone.utc)
    return (expires - now).days


def _access_code(exc: HttpResponseError) -> str:
    """Key Vault puts the reason for a 403 in innererror.code (ForbiddenByFirewall, ForbiddenByRbac, ...)."""
    inner = getattr(getattr(exc, "error", None), "innererror", None)
    inner_code = inner.get("code") if isinstance(inner, dict) else None
    return utils.s(inner_code) or utils.error_code(exc)


def collect_vault_uris(subscription_id: str) -> tuple:
    """Return ([(vault_name, vault_uri)], errors); list_by_subscription carries vaultUri, so no per-vault get."""
    client = utils.get_azure_client("keyvault", subscription_id)
    log.info("Listing all key vaults in subscription %s", subscription_id)
    uris = []
    errors: list = []
    for vault in client.vaults.list_by_subscription():
        uri = vault.properties.vault_uri if vault.properties else ""
        if uri:
            uris.append((vault.name, uri))
        else:
            log.warning("Vault %s listed without a vaultUri; data-plane objects skipped", vault.name)
    return uris, errors


def _collect_keys(vault_name: str, uri: str, credential) -> tuple:
    """Return (rows, access): access is ACCESS_OK or the HttpResponseError that blocked the listing."""
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
    except HttpResponseError as exc:
        log.warning("Keys unreadable for vault %s: %s", vault_name, exc)
        return rows, exc
    return rows, ACCESS_OK


def _collect_secrets(vault_name: str, uri: str, credential) -> tuple:
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
    except HttpResponseError as exc:
        log.warning("Secrets unreadable for vault %s: %s", vault_name, exc)
        return rows, exc
    return rows, ACCESS_OK


def _collect_certificates(vault_name: str, uri: str, credential) -> tuple:
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
    except HttpResponseError as exc:
        log.warning("Certificates unreadable for vault %s: %s", vault_name, exc)
        return rows, exc
    return rows, ACCESS_OK


def _access_cell(vault_name: str, operation: str, access, errors: list) -> str:
    if access == ACCESS_OK:
        return ACCESS_OK
    record = utils.error_record(vault_name, operation, access)
    record["Error Code"] = _access_code(access)
    errors.append(record)
    return record["Error Code"]


def collect_vault_objects(vault_uris: list, credential, errors: list) -> tuple:
    """Return (key_rows, secret_rows, cert_rows, access_rows); every unreadable object type lands in errors."""
    key_rows, secret_rows, cert_rows, access_rows = [], [], [], []
    for vault_name, uri in vault_uris:
        log.info("Reading data-plane objects for vault %s", vault_name)
        keys, key_access = _collect_keys(vault_name, uri, credential)
        secrets, secret_access = _collect_secrets(vault_name, uri, credential)
        certs, cert_access = _collect_certificates(vault_name, uri, credential)
        key_rows.extend(keys)
        secret_rows.extend(secrets)
        cert_rows.extend(certs)
        access_rows.append({
            "Vault": vault_name,
            "Keys": _access_cell(vault_name, "list_properties_of_keys", key_access, errors),
            "Secrets": _access_cell(vault_name, "list_properties_of_secrets", secret_access, errors),
            "Certificates": _access_cell(
                vault_name, "list_properties_of_certificates", cert_access, errors
            ),
        })
    return key_rows, secret_rows, cert_rows, access_rows


def _unreadable_count(access_rows: list) -> int:
    return sum(
        1 for row in access_rows
        if any(row[column] != ACCESS_OK for column in ACCESS_COLUMNS[1:])
    )


def main(subscription_id: str, subscription_name: str) -> utils.ExportResult:
    environment = utils.detect_environment()
    if not utils.is_service_available_in_environment("keyvault", environment):
        sys.exit(0)

    vault_uris, errors = collect_vault_uris(subscription_id)
    if not vault_uris and not errors:
        raise utils.NoResourcesFound("key vaults")

    credential = utils.get_credential()
    key_rows, secret_rows, cert_rows, access_rows = collect_vault_objects(
        vault_uris, credential, errors
    )
    unreadable = _unreadable_count(access_rows)

    filename = utils.create_export_filename(subscription_name, "key-vault-objects", "all")
    utils.save_multiple_dataframes_to_excel(
        {
            "Keys": pd.DataFrame(key_rows),
            "Secrets": pd.DataFrame(secret_rows),
            "Certificates": pd.DataFrame(cert_rows),
            "Vault Access": pd.DataFrame(access_rows, columns=ACCESS_COLUMNS),
        },
        filename,
        errors=errors,
    )
    print(
        f"Exported {len(key_rows)} key(s), {len(secret_rows)} secret(s), "
        f"{len(cert_rows)} certificate(s) across {len(vault_uris)} vault(s) → {filename}"
    )
    if unreadable:
        print(f"{unreadable} vault(s) partly or wholly unreadable — see the Vault Access sheet.")
    log.info(
        "Export complete: %d keys, %d secrets, %d certs, %d unreadable vaults",
        len(key_rows), len(secret_rows), len(cert_rows), unreadable,
    )
    return utils.ExportResult(
        rows=len(key_rows) + len(secret_rows) + len(cert_rows) + len(access_rows),
        filename=filename,
        errors=errors,
    )


if __name__ == "__main__":
    import runner

    runner.run_exporter(main, "key-vault-objects")
