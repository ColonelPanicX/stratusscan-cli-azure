#!/usr/bin/env python3
"""
StratusScan-Azure — interactive configuration.

  • Detects active Azure cloud (Public / USGov)
  • Lists accessible subscriptions and tenants
  • Lets the user pick a default scope (all / selected)
  • Writes config.json (next to this script)

Run:  python configure.py
"""

import json
import sys
from pathlib import Path

_root = Path(__file__).parent.absolute()
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

from sslib.auth import get_credential
from sslib.cloud import arm_scope_for_cloud, detect_cloud
from sslib.config import load_config, save_config
from sslib.subscriptions import list_subscriptions, list_tenants


def _prompt(prompt: str, default: str = "") -> str:
    suffix = f" [{default}]" if default else ""
    val = input(f"{prompt}{suffix}: ").strip()
    return val or default


def main() -> int:
    print("=" * 70)
    print("  STRATUSSCAN-AZURE — CONFIGURATION")
    print("=" * 70)

    cloud = detect_cloud()
    print(f"\nDetected cloud: {cloud['name']}  (Graph: {cloud['graph_endpoint']})")

    print("\nResolving credentials...")
    try:
        credential = get_credential()
        # Force a token fetch so failures surface here, not deeper in the workflow.
        credential.get_token(arm_scope_for_cloud())
    except Exception as e:
        print(f"\n  ERROR: could not authenticate ({e})")
        print("  In Cloud Shell this should be automatic. On a dev box, run: az login")
        return 1

    print("Listing tenants...")
    tenants = list_tenants(credential)
    for t in tenants:
        print(f"  - {t['id']}  ({t['default_domain'] or t['name']})")

    print("\nListing subscriptions...")
    subs = list_subscriptions(credential)
    if not subs:
        print("  (none — your identity has no role assignments)")
        return 1

    for i, s in enumerate(subs, 1):
        print(f"  [{i:>2}] {s['name']}  ({s['id']})  state={s['state']}")

    existing = load_config()
    cfg = {
        "tenant_name": existing.get("tenant_name") or _prompt(
            "\nFriendly tenant label", default="AZURE-TENANT"
        ),
        "subscription_mappings": existing.get("subscription_mappings", {}),
        "default_scope": existing.get("default_scope", {"mode": "all"}),
        "azure_cloud": cloud["name"],
        "output_preferences": existing.get(
            "output_preferences",
            {"use_clouddrive_in_cloud_shell": True, "compress_after_export": False},
        ),
    }

    print("\nMap subscription IDs to friendly names? [y/N]")
    if input("> ").strip().lower() == "y":
        for s in subs:
            current = cfg["subscription_mappings"].get(s["id"], "")
            label = _prompt(f"  {s['name']} ({s['id']})", default=current)
            if label:
                cfg["subscription_mappings"][s["id"]] = label

    print("\nDefault scope:")
    print("  [1] all       — every Enabled subscription (default)")
    print("  [2] selected  — only specific subscription IDs")
    mode_choice = _prompt("  choose", default="1")
    if mode_choice == "2":
        print("  Enter comma-separated subscription numbers (e.g. 1,3,5):")
        raw = input("> ").strip()
        indices = []
        for tok in raw.split(","):
            tok = tok.strip()
            if not tok:
                continue
            try:
                i = int(tok) - 1
            except ValueError:
                print(f"  warn: '{tok}' is not a number — skipping")
                continue
            if 0 <= i < len(subs):
                indices.append(i)
            else:
                print(f"  warn: subscription #{tok} out of range (1..{len(subs)}) — skipping")

        if indices:
            cfg["default_scope"] = {
                "mode": "selected",
                "selected_subscription_ids": [subs[i]["id"] for i in indices],
            }
        else:
            print("  no valid selections — keeping mode=all")
            cfg["default_scope"] = {"mode": "all"}
    else:
        cfg["default_scope"] = {"mode": "all"}

    if save_config(cfg):
        print("\n✔ Saved config.json")
        return 0
    print("\n✘ Failed to save config.json")
    return 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\nCancelled.")
        sys.exit(130)
