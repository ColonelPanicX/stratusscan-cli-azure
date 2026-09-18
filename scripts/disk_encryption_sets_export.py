#!/usr/bin/env python3
"""StratusScanCLI-Azure — Disk Encryption Sets Export

A disk encryption set is the customer-managed-key binding for managed disks,
snapshots and images. One subscription-wide listing
(compute.disk_encryption_sets.list()).

Consumer counts come from three more subscription-wide listings — disks,
snapshots and images — matched on the encryption set ID each resource already
carries. compute.disk_encryption_sets.list_associated_resources() would answer
the same question with one call per set, so the sub-level listings are used
instead: three calls total instead of one per set.

Key material is never exported. The active key is reported as its Key Vault
key URL and the source vault ID — identifiers, not the key — and this exporter
never touches the Key Vault data plane.
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

COLUMNS = [
    "Name", "Resource Group", "Location", "Encryption Type",
    "Active Key Vault ID", "Active Key URL", "Previous Key Count",
    "Rotation To Latest Key Version Enabled", "Last Key Rotation",
    "Auto Key Rotation Error", "Identity Type", "Identity Principal ID",
    "Federated Client ID", "Disks Using", "Snapshots Using", "Images Using",
    "Provisioning State", "Tags",
]


def collect_encryption_sets(client) -> list:
    log.info("Listing disk encryption sets")
    return list(client.disk_encryption_sets.list())


def _disk_encryption_set_id(resource) -> str:
    encryption = getattr(resource, "encryption", None)
    return utils.s(getattr(encryption, "disk_encryption_set_id", None))


def _image_encryption_set_ids(image) -> list[str]:
    storage_profile = getattr(image, "storage_profile", None)
    disks = [getattr(storage_profile, "os_disk", None)]
    disks.extend(getattr(storage_profile, "data_disks", None) or [])
    ids = []
    for disk in disks:
        reference = getattr(disk, "disk_encryption_set", None)
        set_id = utils.s(getattr(reference, "id", None))
        if set_id:
            ids.append(set_id)
    return ids


def count_consumers(client, errors: list) -> dict[str, dict[str, int]]:
    """Return {lower-cased encryption set ID: {"Disks Using": n, ...}}."""
    counts: dict[str, dict[str, int]] = {}

    def record(set_id: str, column: str) -> None:
        if not set_id:
            return
        bucket = counts.setdefault(
            set_id.lower(), {"Disks Using": 0, "Snapshots Using": 0, "Images Using": 0}
        )
        bucket[column] += 1

    for column, operation, listing, extract in (
        ("Disks Using", "disks.list", client.disks.list,
         lambda r: [_disk_encryption_set_id(r)]),
        ("Snapshots Using", "snapshots.list", client.snapshots.list,
         lambda r: [_disk_encryption_set_id(r)]),
        ("Images Using", "images.list", client.images.list, _image_encryption_set_ids),
    ):
        try:
            resources = list(listing())
        except HttpResponseError as e:
            errors.append(utils.error_record(column, operation, e))
            log.warning("Failed to list resources for the %s column: %s", column, e)
            continue
        for resource in resources:
            for set_id in extract(resource):
                record(set_id, column)
    return counts


def _rotation_error(encryption_set) -> str:
    error = getattr(encryption_set, "auto_key_rotation_error", None)
    code = utils.s(getattr(error, "code", None))
    message = utils.s(getattr(error, "message", None))
    return f"{code}: {message}".strip(": ") if (code or message) else ""


def _timestamp(value: Any) -> str:
    return value.strftime("%Y-%m-%d %H:%M:%S") if hasattr(value, "strftime") else utils.s(value)


def build_row(encryption_set, counts: dict[str, dict[str, int]]) -> dict[str, Any]:
    set_id = utils.s(getattr(encryption_set, "id", None))
    active_key = getattr(encryption_set, "active_key", None)
    source_vault = getattr(active_key, "source_vault", None)
    identity = getattr(encryption_set, "identity", None)
    tags = getattr(encryption_set, "tags", None) or {}
    usage = counts.get(set_id.lower(), {})

    return {
        "Name": utils.s(getattr(encryption_set, "name", None)),
        "Resource Group": utils.extract_resource_group(set_id),
        "Location": utils.s(getattr(encryption_set, "location", None)),
        "Encryption Type": utils.s(getattr(encryption_set, "encryption_type", None)),
        "Active Key Vault ID": utils.s(getattr(source_vault, "id", None)),
        "Active Key URL": utils.s(getattr(active_key, "key_url", None)),
        "Previous Key Count": len(getattr(encryption_set, "previous_keys", None) or []),
        "Rotation To Latest Key Version Enabled": (
            "Yes" if getattr(encryption_set, "rotation_to_latest_key_version_enabled", False)
            else "No"
        ),
        "Last Key Rotation": _timestamp(
            getattr(encryption_set, "last_key_rotation_timestamp", None)
        ),
        "Auto Key Rotation Error": _rotation_error(encryption_set),
        "Identity Type": utils.s(getattr(identity, "type", None)),
        "Identity Principal ID": utils.s(getattr(identity, "principal_id", None)),
        "Federated Client ID": utils.s(getattr(encryption_set, "federated_client_id", None)),
        "Disks Using": usage.get("Disks Using", 0),
        "Snapshots Using": usage.get("Snapshots Using", 0),
        "Images Using": usage.get("Images Using", 0),
        "Provisioning State": utils.s(getattr(encryption_set, "provisioning_state", None)),
        "Tags": "; ".join(f"{k}={v}" for k, v in tags.items()),
    }


def main(subscription_id: str, subscription_name: str) -> utils.ExportResult:
    environment = utils.detect_environment()
    if not utils.is_service_available_in_environment("compute", environment):
        sys.exit(0)

    client = utils.get_azure_client("compute", subscription_id)
    encryption_sets = collect_encryption_sets(client)
    if not encryption_sets:
        raise utils.NoResourcesFound("disk encryption sets")

    errors: list = []
    counts = count_consumers(client, errors)
    rows = [build_row(encryption_set, counts) for encryption_set in encryption_sets]

    df = pd.DataFrame(rows, columns=COLUMNS)
    filename = utils.create_export_filename(subscription_name, "disk-encryption-sets", "all")
    utils.save_dataframe_to_excel(df, filename, sheet_name="Disk Encryption Sets", errors=errors)

    unused = sum(
        1 for row in rows
        if row["Disks Using"] == 0 and row["Snapshots Using"] == 0 and row["Images Using"] == 0
    )
    print(
        f"Exported {len(rows)} disk encryption set(s); {unused} with no consumers → {filename}"
    )
    log.info("Export complete: %d disk encryption sets, %d unused", len(rows), unused)
    return utils.ExportResult(rows=len(rows), filename=filename, errors=errors)


if __name__ == "__main__":
    import runner

    runner.run_exporter(main, "disk-encryption-sets")
