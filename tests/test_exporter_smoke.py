"""Import-time and empty-subscription smoke for every exporter and both entry points. No live Azure.

- Importing any module writes nothing under logs/ or output/, runs no pip and builds no client (F-7).
- main() against a client whose every listing is empty raises utils.NoResourcesFound or returns an
  ExportResult without crashing — the cheapest check for attribute typos on the empty path.
- The Python floor declared in pyproject.toml is 3.10 everywhere it is stated.
"""

import importlib
import importlib.util
import re
import subprocess
import sys
from pathlib import Path

import pytest

import bootstrap
import utils

ROOT = Path(__file__).parent.parent
SCRIPTS_DIR = ROOT / "scripts"
EXPORTERS = sorted(SCRIPTS_DIR.glob("*_export.py"))
ENTRY_POINTS = [ROOT / "stratusscan.py", ROOT / "configure.py"]

sys.path.insert(0, str(SCRIPTS_DIR))


class EmptyClient:
    """Stand-in for any azure-mgmt client on a subscription with nothing in it.

    Attribute access chains indefinitely, every list*() call returns [], every other
    call returns another EmptyClient, and every value is falsy/empty so pagination
    loops (next_link) and "if not x" guards terminate.
    """

    def __getattr__(self, name):
        if name.startswith("__"):
            raise AttributeError(name)
        if name.startswith("list"):
            return lambda *args, **kwargs: []
        return EmptyClient()

    def __call__(self, *args, **kwargs):
        return EmptyClient()

    def __bool__(self):
        return False

    def __iter__(self):
        return iter(())

    def __len__(self):
        return 0


def _files_under(root: Path) -> set:
    return {p for p in root.rglob("*") if p.is_file()} if root.exists() else set()


def _load_without_registering(path: Path):
    """Execute a module from source under a throwaway name so the test sees its import-time behavior
    even when another test module already imported it, and without replacing anyone's reference."""
    spec = importlib.util.spec_from_file_location(f"_smoke_{path.stem}", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def no_side_effects(monkeypatch, tmp_path):
    """Route logs/ and output/ to tmp_path; fail on any client build, pip run or dependency bootstrap."""
    monkeypatch.setattr(utils, "__file__", str(tmp_path / "utils.py"))
    monkeypatch.setattr(utils, "get_azure_client", lambda *a, **k: pytest.fail("import must not build a client"))
    monkeypatch.setattr(bootstrap, "ensure_dependencies", lambda: pytest.fail("import must not bootstrap"))
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: pytest.fail("import must not run a subprocess"))
    repo_before = _files_under(ROOT / "logs") | _files_under(ROOT / "output")
    yield tmp_path
    assert _files_under(tmp_path) == set(), "import wrote files"
    assert (_files_under(ROOT / "logs") | _files_under(ROOT / "output")) == repo_before


@pytest.mark.parametrize("path", EXPORTERS + ENTRY_POINTS, ids=[p.stem for p in EXPORTERS + ENTRY_POINTS])
def test_import_writes_nothing_and_touches_no_azure(path, no_side_effects):
    try:
        module = _load_without_registering(path)
    except ImportError as exc:
        pytest.skip(f"SDK package missing: {exc}")
    assert callable(module.main)


def test_module_level_logger_is_the_one_setup_logging_configures(monkeypatch, tmp_path):
    monkeypatch.setattr(utils, "__file__", str(tmp_path / "utils.py"))
    early = utils.get_logger()
    try:
        configured = utils.setup_logging("smoke", subscription_id="12345678-0000-0000-0000-000000000000")
        assert early is configured
        assert any(h.__class__.__name__ == "FileHandler" for h in early.handlers)
        (log_file,) = (tmp_path / "logs").glob("*.log")
        assert log_file.name.startswith("logs-smoke-12345678-")
    finally:
        for handler in list(configured.handlers):
            handler.close()
        configured.handlers = []


@pytest.fixture
def empty_subscription(monkeypatch, tmp_path):
    """Every exporter sees an empty subscription; Excel writes are recorded, not performed."""
    saved = []
    monkeypatch.setattr(utils, "__file__", str(tmp_path / "utils.py"))
    monkeypatch.setattr(utils, "get_azure_client", lambda *a, **k: EmptyClient())
    monkeypatch.setattr(utils, "_get_credential", lambda: pytest.fail("empty path must not need a credential"))
    monkeypatch.setattr(utils, "save_dataframe_to_excel", lambda *a, **k: saved.append(a))
    monkeypatch.setattr(utils, "save_multiple_dataframes_to_excel", lambda *a, **k: saved.append(a))
    monkeypatch.setenv("AZURE_ENVIRONMENT", "AzurePublicCloud")
    monkeypatch.setenv("STRATUSSCAN_AUTO_RUN", "1")
    yield tmp_path
    assert _files_under(tmp_path) == set(), "empty path wrote files"


@pytest.mark.parametrize("path", EXPORTERS, ids=[p.stem for p in EXPORTERS])
def test_main_on_empty_subscription_raises_no_resources_or_returns_result(path, empty_subscription):
    try:
        module = importlib.import_module(path.stem)
    except ImportError as exc:
        pytest.skip(f"SDK package missing: {exc}")

    try:
        result = module.main("00000000-0000-0000-0000-000000000000", "Smoke Sub")
    except utils.NoResourcesFound:
        return
    assert isinstance(result, utils.ExportResult), f"{path.name} returned {type(result).__name__}"


def test_python_floor_is_310_everywhere_it_is_declared():
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert re.search(r'^requires-python = ">=3\.10"$', text, re.M)
    classifiers = re.findall(r'"Programming Language :: Python :: 3\.(\d+)"', text)
    assert classifiers == ["10", "11", "12"]
    assert re.search(r'^target-version = "py310"$', text, re.M)
    assert re.search(r"^target-version = \['py310', 'py311'\]$", text, re.M)
