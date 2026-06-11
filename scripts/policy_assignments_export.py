#!/usr/bin/env python3
"""StratusScanCLI-Azure — Azure Policy Assignments Export"""

import json
import sys
from pathlib import Path

try:
    import utils
except ImportError:
    sys.path.append(str(Path(__file__).parent.parent))
    import utils

import pandas as pd

utils.setup_logging("policy-assignments-export")
utils.log_script_start("policy_assignments_export.py", "Azure Policy Assignments Export")

log = utils.get_logger()


def _build_definition_lookup(client) -> dict:
    lookup = {}
    try:
        for defn in client.policy_definitions.list():
            lookup[defn.id] = {
                "name": defn.display_name or defn.name or "",
                "type": defn.policy_type or "",
                "category": "",
                "description": defn.description or "",
            }
            if defn.metadata:
                cat = defn.metadata.get("category", "")
                lookup[defn.id]["category"] = cat
    except Exception as e:
        log.warning("Failed to build definition lookup: %s", e)

    try:
        for defn in client.policy_definitions.list_built_in():
            if defn.id not in lookup:
                lookup[defn.id] = {
                    "name": defn.display_name or defn.name or "",
                    "type": defn.policy_type or "",
                    "category": "",
                    "description": defn.description or "",
                }
                if defn.metadata:
                    lookup[defn.id]["category"] = defn.metadata.get("category", "")
    except Exception as e:
        log.warning("Failed to list built-in definitions: %s", e)

    return lookup


def _build_initiative_lookup(client) -> dict:
    lookup = {}
    try:
        for defn in client.policy_set_definitions.list():
            lookup[defn.id] = {
                "name": defn.display_name or defn.name or "",
                "type": defn.policy_type or "",
                "category": "",
                "description": defn.description or "",
            }
            if defn.metadata:
                lookup[defn.id]["category"] = defn.metadata.get("category", "")
    except Exception as e:
        log.warning("Failed to build initiative lookup: %s", e)
    return lookup


def _serialize_params(params) -> str:
    if not params:
        return ""
    try:
        simplified = {}
        for k, v in params.items():
            if hasattr(v, "value"):
                simplified[k] = v.value
            else:
                simplified[k] = v
        return json.dumps(simplified, default=str, separators=(",", ":"))
    except Exception:
        return str(params)


def _scope_label(scope: str) -> str:
    if not scope:
        return ""
    if "/managementGroups/" in scope:
        return scope.split("/managementGroups/")[-1]
    resource_group = utils.extract_resource_group(scope)
    if resource_group:
        return resource_group
    if "/subscriptions/" in scope:
        return "subscription"
    return scope


def collect_assignments(subscription_id: str) -> tuple:
    client = utils.get_azure_client("policy", subscription_id)
    log.info("Building policy definition lookups for subscription %s", subscription_id)
    defn_lookup = _build_definition_lookup(client)
    init_lookup = _build_initiative_lookup(client)
    combined_lookup = {**defn_lookup, **init_lookup}

    log.info("Listing policy assignments for subscription %s", subscription_id)
    assignments = list(client.policy_assignments.list())
    return assignments, combined_lookup, client


def collect_custom_definitions(client) -> list:
    log.info("Listing custom policy definitions")
    definitions = []
    try:
        for defn in client.policy_definitions.list():
            if defn.policy_type and defn.policy_type.lower() == "custom":
                definitions.append(defn)
    except Exception as e:
        log.warning("Failed to list custom definitions: %s", e)
    return definitions


def main(subscription_id: str, subscription_name: str) -> None:
    environment = utils.detect_environment()
    if not utils.is_service_available_in_environment("resource", environment):
        sys.exit(0)

    assignments, lookup, client = collect_assignments(subscription_id)

    assignment_rows = []
    for a in assignments:
        defn_id = a.policy_definition_id or ""
        defn_info = lookup.get(defn_id, {})

        assignment_rows.append({
            "Assignment Name": a.display_name or a.name or "",
            "Scope": a.scope or "",
            "Scope Level": _scope_label(a.scope),
            "Policy/Initiative": defn_info.get("name", defn_id.split("/")[-1] if defn_id else ""),
            "Policy Type": defn_info.get("type", ""),
            "Category": defn_info.get("category", ""),
            "Enforcement Mode": a.enforcement_mode or "",
            "Not Scopes": ", ".join(a.not_scopes) if a.not_scopes else "",
            "Parameters": _serialize_params(a.parameters),
            "Description": a.description or defn_info.get("description", ""),
        })

    custom_defs = collect_custom_definitions(client)
    custom_rows = []
    for d in custom_defs:
        category = ""
        if d.metadata:
            category = d.metadata.get("category", "")
        custom_rows.append({
            "Definition Name": d.display_name or d.name or "",
            "Name (ID)": d.name or "",
            "Policy Type": d.policy_type or "",
            "Mode": d.mode or "",
            "Category": category,
            "Description": d.description or "",
        })

    if not assignment_rows and not custom_rows:
        print("No policy assignments or custom definitions found.")
        return

    sheets = {}
    if assignment_rows:
        sheets["Policy Assignments"] = pd.DataFrame(assignment_rows)
    if custom_rows:
        sheets["Custom Definitions"] = pd.DataFrame(custom_rows)

    filename = utils.create_export_filename(subscription_name, "policy-assignments", "all")
    utils.save_multiple_dataframes_to_excel(sheets, filename)
    print(f"Exported {len(assignment_rows)} assignment(s), {len(custom_rows)} custom definition(s) → {filename}")
    log.info("Export complete: %d assignments, %d custom definitions", len(assignment_rows), len(custom_rows))


if __name__ == "__main__":
    sub_id, sub_name = utils.resolve_target_subscription()
    if not sub_id:
        print("ERROR: No subscription configured. Run configure.py first.")
        sys.exit(1)
    main(sub_id, sub_name)
