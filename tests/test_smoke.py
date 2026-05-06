"""
Smoke tests for StratusScan-Azure.

v0.1 scope: import-only structural checks. Resource Graph and Microsoft Graph
are awkward to mock cleanly; a richer mocking strategy lands in v0.2.
"""

import importlib
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


SSLIB_MODULES = [
    "sslib.auth",
    "sslib.cloud",
    "sslib.config",
    "sslib.output",
    "sslib.subscriptions",
]

EXPORTER_MODULES = [
    "scripts.resource_graph_export",
    "scripts.entra_id_export",
    "scripts.rbac_export",
    "scripts.policy_export",
]


@pytest.mark.parametrize("modname", SSLIB_MODULES + EXPORTER_MODULES)
def test_module_imports(modname: str) -> None:
    """Every module imports cleanly with no top-level side effects that fail."""
    mod = importlib.import_module(modname)
    assert mod is not None


def test_cloud_detection_falls_back_to_public() -> None:
    """detect_cloud() returns a usable dict even when az is missing."""
    from sslib.cloud import detect_cloud

    info = detect_cloud()
    assert "name" in info
    assert "graph_endpoint" in info
    assert info["graph_endpoint"].startswith("https://")


def test_output_filename_collision_avoidance(tmp_path, monkeypatch) -> None:
    """make_filename appends -v2, -v3 when same-day file exists."""
    from sslib import output

    monkeypatch.setattr(output, "get_output_dir", lambda: tmp_path)
    f1 = output.make_filename("TEST", "rg", "all")
    (tmp_path / f1).touch()
    f2 = output.make_filename("TEST", "rg", "all")
    assert f1 != f2
    assert "-v2" in f2


def test_subscription_filter_modes() -> None:
    from sslib.subscriptions import filter_subscription_ids

    subs = [
        {"id": "a", "state": "SubscriptionState.enabled"},
        {"id": "b", "state": "SubscriptionState.disabled"},
        {"id": "c", "state": "SubscriptionState.enabled"},
    ]
    assert filter_subscription_ids(subs, {"default_scope": {"mode": "all"}}) == ["a", "c"]
    assert filter_subscription_ids(
        subs,
        {"default_scope": {"mode": "selected", "selected_subscription_ids": ["b", "c"]}},
    ) == ["b", "c"]
