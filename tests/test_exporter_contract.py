"""Every exporter: importable without credentials, exposes main(), and hands off to runner.run_exporter."""

import ast
import importlib
import sys
from pathlib import Path

import pytest

import utils

SCRIPTS_DIR = Path(__file__).parent.parent / "scripts"
EXPORTERS = sorted(p for p in SCRIPTS_DIR.glob("*_export.py"))

sys.path.insert(0, str(SCRIPTS_DIR))


def _main_guard_calls(source: str) -> list:
    """Return the statements inside `if __name__ == "__main__":` as source strings."""
    tree = ast.parse(source)
    for node in tree.body:
        if (
            isinstance(node, ast.If)
            and isinstance(node.test, ast.Compare)
            and isinstance(node.test.left, ast.Name)
            and node.test.left.id == "__name__"
        ):
            return [ast.unparse(stmt) for stmt in node.body]
    return []


def test_registry_matches_disk():
    import stratusscan

    registered = {
        path for _, path in
        stratusscan.TIER1_EXPORTERS + stratusscan.TIER2_EXPORTERS
        + stratusscan.GOVERNANCE_EXPORTERS + stratusscan.MONITORING_EXPORTERS
    }
    assert registered == {p.name for p in EXPORTERS}


@pytest.mark.parametrize("path", EXPORTERS, ids=[p.stem for p in EXPORTERS])
def test_exporter_main_guard_uses_runner(path):
    statements = _main_guard_calls(path.read_text(encoding="utf-8"))
    expected_name = path.stem[: -len("_export")].replace("_", "-")
    assert statements == [
        "import runner",
        f"runner.run_exporter(main, '{expected_name}')",
    ], f"{path.name} must hand off to runner.run_exporter"


@pytest.mark.parametrize("path", EXPORTERS, ids=[p.stem for p in EXPORTERS])
def test_exporter_imports_and_exposes_main(path, monkeypatch):
    monkeypatch.setattr(
        utils, "get_azure_client",
        lambda *a, **k: pytest.fail("import must not build a client"),
    )
    try:
        module = importlib.import_module(path.stem)
    except ImportError as exc:
        pytest.skip(f"SDK package missing: {exc}")
    assert callable(getattr(module, "main", None))
    assert module.main.__code__.co_argcount == 2
    source = path.read_text(encoding="utf-8")
    assert "utils.NoResourcesFound(" in source
    assert "utils.ExportResult(" in source
    assert 'print("No ' not in source, "empty results must raise utils.NoResourcesFound"
