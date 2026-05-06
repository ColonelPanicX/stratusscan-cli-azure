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
            return json.load(f)
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
