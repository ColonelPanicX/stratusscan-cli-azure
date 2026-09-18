"""configure.py wizard — auto-run never prompts, closed stdin never tracebacks, failures exit non-zero."""

import json

import pytest

import configure
import utils

_SUBS = [
    {"id": "sub-a", "name": "Alpha", "state": "Enabled", "tenant_id": "t"},
    {"id": "sub-b", "name": "Bravo", "state": "Enabled", "tenant_id": "t"},
]


@pytest.fixture(autouse=True)
def no_bootstrap_or_log_file(monkeypatch):
    """main() bootstraps dependencies and opens a log file; neither belongs in a unit test."""
    monkeypatch.setattr(configure.bootstrap, "ensure_dependencies", lambda: None)
    monkeypatch.setattr(utils, "setup_logging", lambda *a, **k: utils.get_logger())


@pytest.fixture
def wizard(monkeypatch, tmp_path):
    config_path = tmp_path / "config.json"
    az_dir = tmp_path / "azure"
    az_dir.mkdir()
    (az_dir / "config").write_text("[cloud]\nname = AzureUSGovernment\n", encoding="utf-8")
    monkeypatch.setattr(utils, "_CONFIG_PATH", config_path)
    monkeypatch.setattr(utils, "_config_cache", None)
    monkeypatch.setenv("AZURE_CONFIG_DIR", str(az_dir))
    # configure.main() writes AZURE_ENVIRONMENT; setenv first so teardown restores it
    monkeypatch.setenv("AZURE_ENVIRONMENT", "")
    monkeypatch.delenv("AZURE_ENVIRONMENT")
    monkeypatch.delenv("STRATUSSCAN_AUTO_RUN", raising=False)
    monkeypatch.delenv("STRATUSSCAN_SUBSCRIPTIONS", raising=False)
    monkeypatch.setattr(utils, "list_subscriptions", lambda: list(_SUBS))
    return config_path


def _forbid_input(monkeypatch):
    def fail(prompt=""):
        raise AssertionError("input() must not be called in auto-run")

    monkeypatch.setattr("builtins.input", fail)


def test_auto_run_never_prompts_and_saves_detected_cloud_with_all_subscriptions(wizard, monkeypatch):
    monkeypatch.setenv("STRATUSSCAN_AUTO_RUN", "1")
    _forbid_input(monkeypatch)

    configure.main()

    saved = json.loads(wizard.read_text(encoding="utf-8"))
    assert saved["environment"] == "government"
    assert [sub["id"] for sub in saved["subscriptions"]] == ["sub-a", "sub-b"]
    assert saved["default_subscription_id"] == "sub-a"


def test_auto_run_honors_requested_subscriptions(wizard, monkeypatch):
    monkeypatch.setenv("STRATUSSCAN_AUTO_RUN", "1")
    monkeypatch.setenv("STRATUSSCAN_SUBSCRIPTIONS", "sub-b,sub-unlisted")
    _forbid_input(monkeypatch)

    configure.main()

    saved = json.loads(wizard.read_text(encoding="utf-8"))
    assert [sub["id"] for sub in saved["subscriptions"]] == ["sub-b", "sub-unlisted"]
    assert saved["subscriptions"][0]["name"] == "Bravo"
    assert saved["default_subscription_id"] == "sub-b"


def test_interactive_choice_is_persisted_over_detected_cloud(wizard, monkeypatch):
    choices = iter([1, 2])  # environment → public, subscriptions → all
    monkeypatch.setattr(utils, "prompt_menu", lambda *args, **kwargs: next(choices))

    configure.main()

    saved = json.loads(wizard.read_text(encoding="utf-8"))
    assert saved["environment"] == "public"
    assert len(saved["subscriptions"]) == 2


@pytest.mark.parametrize("menu_choice", [1, 3])
def test_closed_stdin_at_subscription_prompt_returns_nothing_without_traceback(wizard, monkeypatch, menu_choice):
    def closed_stdin(prompt=""):
        raise EOFError

    monkeypatch.setattr("builtins.input", closed_stdin)
    monkeypatch.setattr(utils, "prompt_menu", lambda *args, **kwargs: menu_choice)

    assert configure.select_subscriptions(list(_SUBS)) == []


def test_discovery_failure_prints_cause_and_exits_nonzero(wizard, monkeypatch, capsys):
    def denied():
        raise utils.AzureAccessError(RuntimeError("(AudienceNotSupported) bad audience"), "government")

    monkeypatch.setattr(utils, "list_subscriptions", denied)

    with pytest.raises(SystemExit) as excinfo:
        configure.discover_subscriptions()

    out = capsys.readouterr().out
    assert excinfo.value.code == 1
    assert "AudienceNotSupported" in out
    assert "AzureUSGovernment" in out
    assert "Traceback" not in out


def test_unrecognized_environment_variable_exits_2_before_any_prompt(wizard, monkeypatch, capsys):
    monkeypatch.setenv("AZURE_ENVIRONMENT", "AzureChinaCloud")
    _forbid_input(monkeypatch)

    with pytest.raises(SystemExit) as excinfo:
        configure.main()

    assert excinfo.value.code == 2
    assert "AzureChinaCloud" in capsys.readouterr().out
    assert not wizard.exists()
