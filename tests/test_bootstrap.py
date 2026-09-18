"""bootstrap.ensure_dependencies — metadata probe of every pyproject dependency, quiet pip, no traceback, no loop.

Importing configure/stratusscan must be side-effect free (no pip, no log file); test_exporter_smoke.py proves it.
"""

import subprocess
import sys
from importlib.metadata import PackageNotFoundError

import pytest

import bootstrap
import configure
import utils

PYPROJECT_WITHOUT_TOMLLIB = '''
[project]
name = "x"
dependencies = [
    "azure-identity>=1.15.0,<2.0.0",
    # 25.x splits policy/locks into separate packages, both still beta
    "azure-mgmt-resource>=23.0.0,<25.0.0",  # trailing comment
    'pandas[performance]>=2.0.0',

    "openpyxl>=3.1.0"
]

[project.optional-dependencies]
dev = ["pytest>=7.4.0"]
'''


def _install_harness(monkeypatch):
    calls = []
    exec_calls = []
    monkeypatch.setattr(subprocess, "run", lambda cmd, check: calls.append((cmd, check)))
    monkeypatch.setattr(bootstrap.os, "execv", lambda executable, args: exec_calls.append((executable, args)))
    monkeypatch.delenv(bootstrap._ATTEMPTED_ENV, raising=False)
    return calls, exec_calls


def test_ensure_dependencies_installs_every_pyproject_dependency_when_one_is_missing(monkeypatch):
    calls, exec_calls = _install_harness(monkeypatch)
    deps = ["azure-identity>=1.15.0,<2.0.0", "azure-mgmt-resource>=23.0.0,<25.0.0", "pandas>=2.0.0"]
    monkeypatch.setattr(bootstrap, "_read_pyproject_dependencies", lambda: deps)
    monkeypatch.setattr(bootstrap, "_is_missing", lambda req: req.startswith("azure-mgmt-resource"))

    bootstrap.ensure_dependencies()

    assert calls == [([sys.executable, "-m", "pip", "install", "--quiet", *deps], True)]
    assert exec_calls == [(sys.executable, [sys.executable, *sys.argv])]


def test_ensure_dependencies_skips_pip_when_every_dependency_is_installed(monkeypatch):
    monkeypatch.setattr(bootstrap, "_is_missing", lambda req: False)

    def fail_run(*args, **kwargs):
        raise AssertionError("pip should not run when dependencies are present")

    monkeypatch.setattr(subprocess, "run", fail_run)

    bootstrap.ensure_dependencies()


def test_ensure_dependencies_does_not_loop_after_install_attempt(monkeypatch, capsys):
    monkeypatch.setattr(bootstrap, "_is_missing", lambda req: True)
    monkeypatch.setenv(bootstrap._ATTEMPTED_ENV, "1")

    def fail_run(*args, **kwargs):
        raise AssertionError("pip should not run after bootstrap was already attempted")

    monkeypatch.setattr(subprocess, "run", fail_run)

    bootstrap.ensure_dependencies()

    assert "still unavailable after install" in capsys.readouterr().out


def test_pip_failure_is_one_line_and_exit_2_not_a_traceback(monkeypatch, capsys):
    monkeypatch.setattr(bootstrap, "_is_missing", lambda req: True)
    monkeypatch.delenv(bootstrap._ATTEMPTED_ENV, raising=False)

    def failing_run(cmd, check):
        raise subprocess.CalledProcessError(1, cmd)

    monkeypatch.setattr(subprocess, "run", failing_run)
    monkeypatch.setattr(bootstrap.os, "execv", lambda *a: pytest.fail("must not restart after a failed install"))

    with pytest.raises(SystemExit) as info:
        bootstrap.ensure_dependencies()

    assert info.value.code == 2
    out = capsys.readouterr().out.strip().splitlines()
    assert out[-1].startswith("ERROR: pip install exited 1")
    assert "Traceback" not in "\n".join(out)


def test_is_missing_probes_distribution_metadata_not_imports(monkeypatch):
    probed = []

    def fake_version(name):
        probed.append(name)
        if name == "azure-mgmt-monitor":
            raise PackageNotFoundError(name)
        return "1.0"

    monkeypatch.setattr(bootstrap, "version", fake_version)

    assert bootstrap.missing_dependencies(
        ["azure-identity>=1.15.0,<2.0.0", "azure-mgmt-monitor>=6.0.0,<7.0.0", "pandas[performance]>=2.0.0"]
    ) == ["azure-mgmt-monitor>=6.0.0,<7.0.0"]
    assert probed == ["azure-identity", "azure-mgmt-monitor", "pandas"]


def test_distribution_name_strips_extras_specifiers_and_markers():
    assert bootstrap._distribution_name("pandas[performance]>=2.0.0") == "pandas"
    assert bootstrap._distribution_name("azure-mgmt-resource>=23.0.0,<25.0.0") == "azure-mgmt-resource"
    assert bootstrap._distribution_name('tomli>=2; python_version < "3.11"') == "tomli"
    with pytest.raises(ValueError):
        bootstrap._distribution_name(">=1.0")


def test_every_declared_dependency_has_a_probeable_name():
    for dep in bootstrap._read_pyproject_dependencies():
        assert bootstrap._distribution_name(dep)


def test_fallback_parser_handles_comments_extras_and_quotes():
    assert bootstrap._parse_dependencies_without_tomllib(PYPROJECT_WITHOUT_TOMLLIB) == [
        "azure-identity>=1.15.0,<2.0.0",
        "azure-mgmt-resource>=23.0.0,<25.0.0",
        "pandas[performance]>=2.0.0",
        "openpyxl>=3.1.0",
    ]


def test_fallback_parser_matches_tomllib_on_the_real_pyproject():
    tomllib = pytest.importorskip("tomllib")
    pyproject = bootstrap.Path(bootstrap.__file__).parent / "pyproject.toml"
    with open(pyproject, "rb") as fh:
        expected = tomllib.load(fh)["project"]["dependencies"]
    assert bootstrap._parse_dependencies_without_tomllib(pyproject.read_text(encoding="utf-8")) == expected


def test_dead_dependencies_are_gone():
    names = {bootstrap._distribution_name(dep) for dep in bootstrap._read_pyproject_dependencies()}
    assert "questionary" not in names
    assert "python-dateutil" not in names


def test_resource_dependency_is_capped_below_split_release():
    deps = bootstrap._read_pyproject_dependencies()

    assert "azure-mgmt-resource>=23.0.0,<25.0.0" in deps


def test_resource_clients_use_stable_submodule_paths():
    assert utils._CLIENT_MAP["subscription"] == (
        "azure.mgmt.resource.subscriptions",
        "SubscriptionClient",
        False,
    )
    assert utils._CLIENT_MAP["resource"] == (
        "azure.mgmt.resource.resources",
        "ResourceManagementClient",
        True,
    )


def test_government_clients_use_government_arm_scope(monkeypatch):
    captured = {}

    class Client:
        def __init__(self, credential, **kwargs):
            captured["credential"] = credential
            captured["kwargs"] = kwargs

    monkeypatch.setitem(
        utils._CLIENT_MAP,
        "subscription",
        ("tests.fake_module", "Client", False),
    )
    monkeypatch.setattr(utils, "_get_credential", lambda: "credential")
    monkeypatch.setattr(utils, "detect_environment", lambda: "government")

    def fake_import_module(module_path):
        assert module_path == "tests.fake_module"

        class Module:
            pass

        Module.Client = Client
        return Module

    monkeypatch.setattr("importlib.import_module", fake_import_module)

    utils.get_azure_client("subscription")

    assert captured["credential"] == "credential"
    assert captured["kwargs"]["base_url"] == "https://management.usgovcloudapi.net"
    assert captured["kwargs"]["credential_scopes"] == [
        "https://management.core.usgovcloudapi.net/.default"
    ]


def test_government_storage_client_uses_supported_api_version(monkeypatch):
    captured = {}

    class Client:
        def __init__(self, credential, subscription_id, **kwargs):
            captured["credential"] = credential
            captured["subscription_id"] = subscription_id
            captured["kwargs"] = kwargs

    monkeypatch.setitem(
        utils._CLIENT_MAP,
        "storage",
        ("tests.fake_storage_module", "Client", True),
    )
    monkeypatch.setattr(utils, "_get_credential", lambda: "credential")
    monkeypatch.setattr(utils, "detect_environment", lambda: "government")

    def fake_import_module(module_path):
        assert module_path == "tests.fake_storage_module"

        class Module:
            pass

        Module.Client = Client
        return Module

    monkeypatch.setattr("importlib.import_module", fake_import_module)

    utils.get_azure_client("storage", "sub-id")

    assert captured["subscription_id"] == "sub-id"
    assert captured["kwargs"]["api_version"] == "2025-06-01"


def test_configure_applies_selected_environment_before_subscription_discovery(monkeypatch):
    observed = {}

    monkeypatch.setattr(configure.bootstrap, "ensure_dependencies", lambda: None)
    monkeypatch.setattr(utils, "setup_logging", lambda *a, **k: utils.get_logger())
    monkeypatch.setattr(configure, "select_environment", lambda: "government")
    monkeypatch.setattr(
        configure,
        "discover_subscriptions",
        lambda: observed.setdefault("env", configure.os.environ.get("AZURE_ENVIRONMENT")) or [],
    )
    monkeypatch.setattr(configure, "select_subscriptions", lambda subs: [])
    # configure.main() writes AZURE_ENVIRONMENT; setenv first so teardown restores it
    monkeypatch.setenv("AZURE_ENVIRONMENT", "")
    monkeypatch.delenv("AZURE_ENVIRONMENT")

    configure.main([])

    assert observed["env"] == "AzureUSGovernment"


def test_public_environment_variable_overrides_stale_government_config(monkeypatch):
    monkeypatch.setenv("AZURE_ENVIRONMENT", "AzurePublicCloud")
    monkeypatch.setattr(utils, "get_config", lambda: {"environment": "government"})

    assert utils.detect_environment() == "public"


def test_extract_resource_group_is_case_insensitive_and_safe():
    assert (
        utils.extract_resource_group(
            "/subscriptions/sub/resourcegroups/RG1/providers/Microsoft.Network/firewallPolicies/policy"
        )
        == "RG1"
    )
    assert utils.extract_resource_group("/subscriptions/sub/providers/Microsoft.Network/foo/bar") == ""
    assert utils.extract_resource_group(None) == ""
