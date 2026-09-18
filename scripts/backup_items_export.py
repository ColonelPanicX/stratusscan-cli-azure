#!/usr/bin/env python3
"""StratusScanCLI-Azure — Azure Backup Items & Policies Export

Recovery Services vaults are listed subscription-wide; protected items and
protection policies are child collections listed per vault, so a vault that
answers an error is recorded on the Errors sheet (PARTIAL) and the run
continues.

Three sheets:
  Vaults          — the vault-level CP controls: redundancy, cross-region
                    restore, soft delete, immutability and CMK. Soft delete and
                    storage redundancy come from the backup resource vault
                    config (a separate per-vault GET) because the vault resource
                    itself only carries them from api-version 2023-01-01 onward
                    under securitySettings/redundancySettings.
  Protected Items — what is actually backed up, with last backup status and the
                    latest recovery point.
  Policies        — the schedule and retention behind each policy name.

The protected-item model is polymorphic (AzureIaaSVMProtectedItem,
AzureVmWorkloadProtectedItem, AzureFileshareProtectedItem, …), so every
subtype-only attribute is read with getattr and left blank when the subtype
does not carry it.
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
from azure.core.exceptions import HttpResponseError

log = utils.get_logger()

VAULT_COLUMNS = [
    "Name", "Resource Group", "Location", "SKU", "Tier", "Storage Type",
    "Cross Region Restore", "Soft Delete State", "Soft Delete Retention (days)",
    "Enhanced Security", "Immutability State", "Multi-User Authorization",
    "Encryption Key Source", "Encryption Key URI", "Infrastructure Encryption",
    "Encryption Identity", "Public Network Access", "Provisioning State",
    "Protected Items", "Policies",
]
ITEM_COLUMNS = [
    "Vault", "Vault Resource Group", "Item Name", "Friendly Name",
    "Protected Item Type", "Backup Management Type", "Workload Type",
    "Container Name", "Source Resource ID", "Protection State",
    "Protection Status", "Health Status", "Last Backup Time",
    "Last Backup Status", "Latest Recovery Point", "Policy Name",
    "Soft Delete Retention (days)", "Archive Enabled",
    "Deferred Delete Scheduled",
]
POLICY_COLUMNS = [
    "Vault", "Vault Resource Group", "Policy Name", "Backup Management Type",
    "Policy Type", "Protected Items Count", "Time Zone", "Schedule",
    "Daily Retention", "Weekly Retention", "Monthly Retention",
    "Yearly Retention", "Instant Restore Retention (days)",
]


def _timestamp(value: Any) -> str:
    return value.strftime("%Y-%m-%d %H:%M:%S") if hasattr(value, "strftime") else utils.s(value)


def _own_mapping(model_class: type) -> dict:
    """The discriminator map declared on this class, not the one it inherits."""
    return model_class.__dict__.get("__mapping__") or {}


def _concrete_subtype(model_class: type, discriminator: str) -> type | None:
    for value, subtype in _own_mapping(model_class).items():
        if value == discriminator:
            return subtype
        nested = _concrete_subtype(subtype, discriminator)
        if nested is not None:
            return nested
    return None


def resolve_polymorphic(props: Any, discriminator_attribute: str) -> Any:
    """Return props re-read as its concrete subtype.

    azure-mgmt-recoveryservicesbackup resolves only the first level of the
    protectedItemType discriminator, so an Azure VM item — whose type
    "Microsoft.Compute/virtualMachines" is nested one level below
    AzureIaaSVMProtectedItem — comes back as the base ProtectedItem with every
    subtype-only column (friendly name, protection state, last backup) missing.
    Walking the declared mappings finds the real class and re-reads the same
    wire payload through it.
    """
    if props is None:
        return None
    discriminator = utils.s(getattr(props, discriminator_attribute, None))
    if not discriminator:
        return props
    subtype = _concrete_subtype(type(props), discriminator)
    if subtype is None or subtype is type(props):
        return props
    try:
        return subtype(dict(props))
    except (TypeError, ValueError) as exc:
        log.warning("Could not read %s as %s: %s", discriminator, subtype.__name__, exc)
        return props


def collect_vaults(subscription_id: str) -> list:
    client = utils.get_azure_client("recoveryservices", subscription_id)
    log.info("Listing Recovery Services vaults in subscription %s", subscription_id)
    return list(client.vaults.list_by_subscription_id())


def _vault_config_columns(backup_client, vault_name: str, resource_group: str, errors: list) -> dict[str, str]:
    """Soft delete and storage redundancy, from the vault's backup resource config."""
    blank = {
        "Storage Type": "", "Soft Delete State": "",
        "Soft Delete Retention (days)": "", "Enhanced Security": "",
    }
    try:
        config = backup_client.backup_resource_vault_configs.get(vault_name, resource_group)
    except HttpResponseError as e:
        errors.append(utils.error_record(vault_name, "backup_resource_vault_configs.get", e))
        log.warning("Failed to read the backup vault config for %s: %s", vault_name, e)
        return blank
    props = getattr(config, "properties", None) or config
    return {
        "Storage Type": utils.s(getattr(props, "storage_type", None)),
        "Soft Delete State": utils.s(getattr(props, "soft_delete_feature_state", None)),
        "Soft Delete Retention (days)": utils.s(
            getattr(props, "soft_delete_retention_period_in_days", None)
        ),
        "Enhanced Security": utils.s(getattr(props, "enhanced_security_state", None)),
    }


def _encryption_columns(props) -> dict[str, str]:
    encryption = getattr(props, "encryption", None)
    key_vault = getattr(encryption, "key_vault_properties", None)
    identity = getattr(encryption, "kek_identity", None)
    if getattr(identity, "use_system_assigned_identity", None):
        identity_label = "SystemAssigned"
    else:
        identity_label = utils.s(getattr(identity, "user_assigned_identity", None))
    key_uri = utils.s(getattr(key_vault, "key_uri", None))
    return {
        "Encryption Key Source": "Microsoft.KeyVault" if key_uri else "Microsoft.Backup",
        "Encryption Key URI": key_uri,
        "Infrastructure Encryption": utils.s(
            getattr(encryption, "infrastructure_encryption", None)
        ),
        "Encryption Identity": identity_label,
    }


def build_vault_row(vault, config_columns: dict[str, str], item_count: int, policy_count: int) -> dict[str, Any]:
    props = getattr(vault, "properties", None)
    sku = getattr(vault, "sku", None)
    security = getattr(props, "security_settings", None)
    redundancy = getattr(props, "redundancy_settings", None)
    immutability = getattr(security, "immutability_settings", None)
    soft_delete = getattr(security, "soft_delete_settings", None)

    row = {
        "Name": utils.s(getattr(vault, "name", None)),
        "Resource Group": utils.extract_resource_group(getattr(vault, "id", None)),
        "Location": utils.s(getattr(vault, "location", None)),
        "SKU": utils.s(getattr(sku, "name", None)),
        "Tier": utils.s(getattr(sku, "tier", None)),
        "Cross Region Restore": utils.s(getattr(redundancy, "cross_region_restore", None)),
        "Immutability State": utils.s(getattr(immutability, "state", None)),
        "Multi-User Authorization": utils.s(getattr(security, "multi_user_authorization", None)),
        "Public Network Access": utils.s(getattr(props, "public_network_access", None)),
        "Provisioning State": utils.s(getattr(props, "provisioning_state", None)),
        "Protected Items": item_count,
        "Policies": policy_count,
    }
    row.update(config_columns)
    row.update(_encryption_columns(props))

    # The vault resource carries soft delete too; prefer it when the backup
    # config call was the one that failed.
    if not row["Soft Delete State"]:
        row["Soft Delete State"] = utils.s(getattr(soft_delete, "soft_delete_state", None))
        row["Soft Delete Retention (days)"] = utils.s(
            getattr(soft_delete, "soft_delete_retention_period_in_days", None)
        )
    if not row["Storage Type"]:
        row["Storage Type"] = utils.s(
            getattr(redundancy, "standard_tier_storage_redundancy", None)
        )
    return row


def build_item_row(item, vault_name: str, vault_resource_group: str) -> dict[str, Any]:
    props = resolve_polymorphic(getattr(item, "properties", None), "protected_item_type")
    return {
        "Vault": vault_name,
        "Vault Resource Group": vault_resource_group,
        "Item Name": utils.s(getattr(item, "name", None)),
        "Friendly Name": utils.s(getattr(props, "friendly_name", None)),
        "Protected Item Type": utils.s(getattr(props, "protected_item_type", None)),
        "Backup Management Type": utils.s(getattr(props, "backup_management_type", None)),
        "Workload Type": utils.s(getattr(props, "workload_type", None)),
        "Container Name": utils.s(getattr(props, "container_name", None)),
        "Source Resource ID": utils.s(getattr(props, "source_resource_id", None)),
        "Protection State": utils.s(getattr(props, "protection_state", None)),
        "Protection Status": utils.s(getattr(props, "protection_status", None)),
        "Health Status": utils.s(getattr(props, "health_status", None)),
        "Last Backup Time": _timestamp(getattr(props, "last_backup_time", None)),
        "Last Backup Status": utils.s(getattr(props, "last_backup_status", None)),
        "Latest Recovery Point": _timestamp(getattr(props, "last_recovery_point", None)),
        "Policy Name": utils.s(getattr(props, "policy_name", None)),
        "Soft Delete Retention (days)": utils.s(
            getattr(props, "soft_delete_retention_period_in_days", None)
        ),
        "Archive Enabled": "Yes" if getattr(props, "is_archive_enabled", False) else "No",
        "Deferred Delete Scheduled": (
            "Yes" if getattr(props, "is_scheduled_for_deferred_delete", False) else "No"
        ),
    }


def _retention_text(schedule, *extra_attributes: str) -> str:
    if schedule is None:
        return ""
    duration = getattr(schedule, "retention_duration", None)
    count = utils.s(getattr(duration, "count", None))
    unit = utils.s(getattr(duration, "duration_type", None))
    parts = [f"{count} {unit}".strip()] if count or unit else []
    for attribute in extra_attributes:
        values = getattr(schedule, attribute, None) or []
        if values:
            parts.append(", ".join(utils.s(v) for v in values))
    return " | ".join(part for part in parts if part)


def _schedule_text(schedule_policy) -> str:
    if schedule_policy is None:
        return ""
    frequency = utils.s(getattr(schedule_policy, "schedule_run_frequency", None))
    days = getattr(schedule_policy, "schedule_run_days", None) or []
    times = getattr(schedule_policy, "schedule_run_times", None) or []
    parts = [frequency] if frequency else []
    if days:
        parts.append(", ".join(utils.s(d) for d in days))
    if times:
        parts.append(", ".join(_timestamp(t) for t in times))
    hourly = getattr(schedule_policy, "hourly_schedule", None)
    if hourly is not None:
        interval = utils.s(getattr(hourly, "interval", None))
        if interval:
            parts.append(f"every {interval}h")
    return " | ".join(part for part in parts if part)


def _sub_policy_retention(props):
    """AzureVmWorkload policies hold schedule/retention per sub-protection policy."""
    for sub in getattr(props, "sub_protection_policy", None) or []:
        if getattr(sub, "policy_type", None) is not None and utils.s(sub.policy_type).lower() == "full":
            return sub
    sub_policies = getattr(props, "sub_protection_policy", None) or []
    return sub_policies[0] if sub_policies else None


def build_policy_row(policy, vault_name: str, vault_resource_group: str) -> dict[str, Any]:
    props = resolve_polymorphic(getattr(policy, "properties", None), "backup_management_type")
    schedule_policy = getattr(props, "schedule_policy", None)
    retention = getattr(props, "retention_policy", None)
    if schedule_policy is None and retention is None:
        sub = _sub_policy_retention(props)
        schedule_policy = getattr(sub, "schedule_policy", None)
        retention = getattr(sub, "retention_policy", None)

    return {
        "Vault": vault_name,
        "Vault Resource Group": vault_resource_group,
        "Policy Name": utils.s(getattr(policy, "name", None)),
        "Backup Management Type": utils.s(getattr(props, "backup_management_type", None)),
        "Policy Type": utils.s(
            getattr(props, "policy_type", None) or getattr(props, "work_load_type", None)
        ),
        "Protected Items Count": utils.s(getattr(props, "protected_items_count", None)),
        "Time Zone": utils.s(getattr(props, "time_zone", None)),
        "Schedule": _schedule_text(schedule_policy),
        "Daily Retention": _retention_text(getattr(retention, "daily_schedule", None)),
        "Weekly Retention": _retention_text(
            getattr(retention, "weekly_schedule", None), "days_of_the_week"
        ),
        "Monthly Retention": _retention_text(getattr(retention, "monthly_schedule", None)),
        "Yearly Retention": _retention_text(
            getattr(retention, "yearly_schedule", None), "months_of_year"
        ),
        "Instant Restore Retention (days)": utils.s(
            getattr(props, "instant_rp_retention_range_in_days", None)
        ),
    }


def collect_vault_children(backup_client, vaults: list, errors: list) -> tuple[list, list, list]:
    """Return (vault rows, protected item rows, policy rows) across every vault."""
    vault_rows, item_rows, policy_rows = [], [], []
    for vault in vaults:
        vault_name = utils.s(getattr(vault, "name", None))
        resource_group = utils.extract_resource_group(getattr(vault, "id", None))
        scope = utils.s(getattr(vault, "id", None)) or vault_name

        try:
            items = list(backup_client.backup_protected_items.list(vault_name, resource_group))
        except HttpResponseError as e:
            errors.append(utils.error_record(scope, "backup_protected_items.list", e))
            log.warning("Failed to list protected items in vault %s: %s", vault_name, e)
            items = []

        try:
            policies = list(backup_client.backup_policies.list(vault_name, resource_group))
        except HttpResponseError as e:
            errors.append(utils.error_record(scope, "backup_policies.list", e))
            log.warning("Failed to list backup policies in vault %s: %s", vault_name, e)
            policies = []

        config_columns = _vault_config_columns(backup_client, vault_name, resource_group, errors)

        item_rows.extend(build_item_row(item, vault_name, resource_group) for item in items)
        policy_rows.extend(
            build_policy_row(policy, vault_name, resource_group) for policy in policies
        )
        vault_rows.append(build_vault_row(vault, config_columns, len(items), len(policies)))
    return vault_rows, item_rows, policy_rows


def main(subscription_id: str, subscription_name: str) -> utils.ExportResult:
    environment = utils.detect_environment()
    if not utils.is_service_available_in_environment("recoveryservicesbackup", environment):
        sys.exit(0)

    vaults = collect_vaults(subscription_id)
    if not vaults:
        raise utils.NoResourcesFound("Recovery Services vaults")

    backup_client = utils.get_azure_client("recoveryservicesbackup", subscription_id)
    errors: list = []
    vault_rows, item_rows, policy_rows = collect_vault_children(backup_client, vaults, errors)

    sheets = {
        "Vaults": pd.DataFrame(vault_rows, columns=VAULT_COLUMNS),
        "Protected Items": pd.DataFrame(item_rows, columns=ITEM_COLUMNS),
        "Policies": pd.DataFrame(policy_rows, columns=POLICY_COLUMNS),
    }
    filename = utils.create_export_filename(subscription_name, "backup-items", "all")
    utils.save_multiple_dataframes_to_excel(sheets, filename, errors=errors)

    print(
        f"Exported {len(item_rows)} protected item(s) and {len(policy_rows)} policy(ies) "
        f"across {len(vault_rows)} vault(s) → {filename}"
    )
    log.info(
        "Export complete: %d vaults, %d protected items, %d policies",
        len(vault_rows), len(item_rows), len(policy_rows),
    )
    return utils.ExportResult(rows=len(item_rows), filename=filename, errors=errors)


if __name__ == "__main__":
    import runner

    runner.run_exporter(main, "backup-items")
