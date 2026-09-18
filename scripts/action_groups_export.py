#!/usr/bin/env python3
"""StratusScanCLI-Azure — Action Groups Export

Webhook service URIs are written without their query string, user-info or
fragment: those parts routinely carry shared-secret tokens.
"""

import sys
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

try:
    import utils
except ImportError:
    sys.path.append(str(Path(__file__).parent.parent))
    import utils

import pandas as pd

utils.setup_logging("action-groups-export")
utils.log_script_start("action_groups_export.py", "Action Groups Export")

log = utils.get_logger()

_REDACTED_MARKER = "?…redacted"


def _redact_uri(uri: str) -> str:
    """Return scheme://host[:port]/path, with a marker when a query, fragment or user-info was dropped."""
    if not uri:
        return ""
    try:
        parts = urlsplit(uri)
    except ValueError:
        return _REDACTED_MARKER
    host = parts.hostname or ""
    if parts.port:
        host = f"{host}:{parts.port}"
    stripped = urlunsplit((parts.scheme, host, parts.path, "", ""))
    if parts.query or parts.fragment or parts.username or parts.password:
        return stripped + _REDACTED_MARKER
    return stripped


def _format_receivers(receivers, name_attr: str, detail_attr: str = "") -> str:
    if not receivers:
        return ""
    parts = []
    for r in receivers:
        name = utils.s(getattr(r, name_attr, None))
        detail = utils.s(getattr(r, detail_attr, None)) if detail_attr else ""
        if detail:
            parts.append(f"{name} ({detail})")
        else:
            parts.append(name)
    return ", ".join(parts)


def _format_webhook_receivers(receivers) -> str:
    if not receivers:
        return ""
    parts = []
    for r in receivers:
        name = utils.s(getattr(r, "name", None))
        uri = _redact_uri(utils.s(getattr(r, "service_uri", None)))
        parts.append(f"{name} ({uri})" if uri else name)
    return ", ".join(parts)


def _format_event_hub_receivers(receivers) -> str:
    if not receivers:
        return ""
    parts = []
    for r in receivers:
        name = utils.s(getattr(r, "name", None))
        namespace = utils.s(getattr(r, "event_hub_name_space", None))
        hub = utils.s(getattr(r, "event_hub_name", None))
        target = "/".join(p for p in (namespace, hub) if p)
        parts.append(f"{name} ({target})" if target else name)
    return ", ".join(parts)


def _build_row(ag) -> dict:
    ag_id = utils.s(getattr(ag, "id", None))
    return {
        "Action Group Name": utils.s(getattr(ag, "name", None)),
        "Resource Group": utils.extract_resource_group(ag_id),
        "Short Name": utils.s(getattr(ag, "group_short_name", None)),
        "Enabled": "Yes" if getattr(ag, "enabled", True) else "No",
        "Email Receivers": _format_receivers(
            getattr(ag, "email_receivers", None), "name", "email_address"
        ),
        "SMS Receivers": _format_receivers(
            getattr(ag, "sms_receivers", None), "name", "phone_number"
        ),
        "Webhook Receivers": _format_webhook_receivers(getattr(ag, "webhook_receivers", None)),
        "Azure App Push": _format_receivers(
            getattr(ag, "azure_app_push_receivers", None), "name", "email_address"
        ),
        "ITSM Receivers": _format_receivers(
            getattr(ag, "itsm_receivers", None), "name"
        ),
        "Automation Runbook": _format_receivers(
            getattr(ag, "automation_runbook_receivers", None), "name"
        ),
        "Azure Function": _format_receivers(
            getattr(ag, "azure_function_receivers", None), "name", "function_name"
        ),
        "Logic App": _format_receivers(
            getattr(ag, "logic_app_receivers", None), "name"
        ),
        "ARM Role Receivers": _format_receivers(
            getattr(ag, "arm_role_receivers", None), "name", "role_id"
        ),
        "Voice Receivers": _format_receivers(
            getattr(ag, "voice_receivers", None), "name", "phone_number"
        ),
        "Event Hub Receivers": _format_event_hub_receivers(getattr(ag, "event_hub_receivers", None)),
    }


def collect_action_groups(subscription_id: str) -> list:
    client = utils.get_azure_client("monitor", subscription_id)
    log.info("Listing action groups for subscription %s", subscription_id)

    rows = []
    try:
        for ag in client.action_groups.list_by_subscription_id():
            rows.append(_build_row(ag))
    except Exception as e:
        log.warning("Failed to list action groups: %s", e)

    return rows


def main(subscription_id: str, subscription_name: str) -> None:
    environment = utils.detect_environment()
    if not utils.is_service_available_in_environment("resource", environment):
        sys.exit(0)

    rows = collect_action_groups(subscription_id)

    if not rows:
        print("No action groups found.")
        return

    df = pd.DataFrame(rows)
    filename = utils.create_export_filename(subscription_name, "action-groups", "all")
    utils.save_dataframe_to_excel(df, filename)
    print(f"Exported {len(rows)} action group(s) → {filename}")
    log.info("Export complete: %d action groups", len(rows))


if __name__ == "__main__":
    sub_id, sub_name = utils.resolve_target_subscription()
    if not sub_id:
        print("ERROR: No subscription configured. Run configure.py first.")
        sys.exit(1)
    main(sub_id, sub_name)
