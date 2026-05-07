"""
sslib.config — Load config.json (subscription mappings, default scope, etc.).
"""

import json
import logging
from pathlib import Path
from typing import Any, Dict

logger = logging.getLogger(__name__)


def _config_path() -> Path:
    return Path(__file__).parent.parent / "config.json"


def _strip_meta_keys(obj: Any) -> Any:
    # Drop keys starting with "__" so template comment fields (__comment,
    # __mode_options, etc.) don't survive a load → save round-trip.
    if isinstance(obj, dict):
        return {k: _strip_meta_keys(v) for k, v in obj.items() if not k.startswith("__")}
    if isinstance(obj, list):
        return [_strip_meta_keys(v) for v in obj]
    return obj


def load_config() -> Dict[str, Any]:
    """
    Load config.json. Returns {} if the file is missing or unreadable.
    """
    path = _config_path()
    if not path.exists():
        logger.debug("config.json not found at %s — returning empty config", path)
        return {}
    try:
        with path.open(encoding="utf-8") as f:
            return _strip_meta_keys(json.load(f))
    except Exception as e:
        logger.warning("Could not read config.json: %s", e)
        return {}


def save_config(data: Dict[str, Any]) -> bool:
    """
    Atomically write config.json.
    """
    path = _config_path()
    tmp = path.with_suffix(".json.tmp")
    try:
        with tmp.open("w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        tmp.replace(path)
        return True
    except Exception as e:
        logger.error("Failed to write config.json: %s", e)
        return False


def get_subscription_label(config: Dict[str, Any], subscription_id: str, fallback: str) -> str:
    """
    Resolve a subscription ID to its friendly name from config, or return fallback.
    """
    mappings = (config or {}).get("subscription_mappings", {}) or {}
    return mappings.get(subscription_id, fallback)


def resolve_scope_label(config: Dict[str, Any], subscription_ids: list) -> str:
    """
    Pick the right scope label for an output filename.

    Single sub in scope → that sub's mapped friendly name (falls back to tenant_name).
    Multi-sub or empty  → the tenant label.
    """
    tenant = (config or {}).get("tenant_name") or "AZURE-TENANT"
    if subscription_ids and len(subscription_ids) == 1:
        return get_subscription_label(config, subscription_ids[0], tenant)
    return tenant
