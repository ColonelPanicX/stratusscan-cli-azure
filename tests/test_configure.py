"""configure.py wizard — auto-run never prompts, closed stdin never tracebacks, failures exit non-zero."""

import json

import pytest

import cli_ui
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

    configure.main([])

    saved = json.loads(wizard.read_text(encoding="utf-8"))
    assert saved["environment"] == "government"
    assert [sub["id"] for sub in saved["subscriptions"]] == ["sub-a", "sub-b"]
    assert saved["default_subscription_id"] == "sub-a"


def test_auto_run_honors_requested_subscriptions(wizard, monkeypatch):
    monkeypatch.setenv("STRATUSSCAN_AUTO_RUN", "1")
    monkeypatch.setenv("STRATUSSCAN_SUBSCRIPTIONS", "sub-b,sub-unlisted")
    _forbid_input(monkeypatch)

    configure.main([])

    saved = json.loads(wizard.read_text(encoding="utf-8"))
    assert [sub["id"] for sub in saved["subscriptions"]] == ["sub-b", "sub-unlisted"]
    assert saved["subscriptions"][0]["name"] == "Bravo"
    assert saved["default_subscription_id"] == "sub-b"


def test_interactive_choice_is_persisted_over_detected_cloud(wizard, monkeypatch):
    choices = iter([1, 3])  # environment → public, subscriptions → all
    monkeypatch.setattr(cli_ui, "prompt_menu", lambda *args, **kwargs: next(choices))

    configure.main([])

    saved = json.loads(wizard.read_text(encoding="utf-8"))
    assert saved["environment"] == "public"
    assert len(saved["subscriptions"]) == 2


@pytest.mark.parametrize("menu_choice", [1, 2, 4])
def test_closed_stdin_at_subscription_prompt_quits_without_traceback(wizard, monkeypatch, menu_choice):
    def closed_stdin(prompt=""):
        raise EOFError

    monkeypatch.setattr("builtins.input", closed_stdin)
    monkeypatch.setattr(cli_ui, "prompt_menu", lambda *args, **kwargs: menu_choice)

    with pytest.raises(cli_ui.QuitRequested):
        configure.select_subscriptions(list(_SUBS))


def test_quit_at_a_prompt_leaves_config_unwritten(wizard, monkeypatch, capsys):
    def quit_now(*args, **kwargs):
        raise cli_ui.QuitRequested

    monkeypatch.setattr(cli_ui, "prompt_menu", quit_now)

    with pytest.raises(SystemExit) as excinfo:
        configure.main([])

    assert excinfo.value.code == 0
    assert "Goodbye." in capsys.readouterr().out
    assert not wizard.exists()


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
        configure.main([])

    assert excinfo.value.code == 2
    assert "AzureChinaCloud" in capsys.readouterr().out
    assert not wizard.exists()


# ---------------------------------------------------------------------------
# Multi-select and GUID validation
# ---------------------------------------------------------------------------

_GUID_A = "11111111-2222-3333-4444-555555555555"
_GUID_B = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"


def _answers(monkeypatch, *values):
    supplied = iter(values)
    monkeypatch.setattr("builtins.input", lambda prompt="": next(supplied))


def test_multi_select_takes_comma_separated_numbers(wizard, monkeypatch):
    monkeypatch.setattr(cli_ui, "prompt_menu", lambda *a, **k: 2)
    _answers(monkeypatch, "2, 1")

    assert [s["id"] for s in configure.select_subscriptions(list(_SUBS))] == ["sub-b", "sub-a"]


def test_multi_select_reprompts_on_an_out_of_range_number(wizard, monkeypatch, capsys):
    monkeypatch.setattr(cli_ui, "prompt_menu", lambda *a, **k: 2)
    _answers(monkeypatch, "1,9", "abc", "1")

    assert [s["id"] for s in configure.select_subscriptions(list(_SUBS))] == ["sub-a"]
    assert capsys.readouterr().out.count("Invalid selection") == 2


def test_single_select_still_returns_one_subscription(wizard, monkeypatch):
    monkeypatch.setattr(cli_ui, "prompt_menu", lambda *a, **k: 1)
    _answers(monkeypatch, "2")

    assert [s["id"] for s in configure.select_subscriptions(list(_SUBS))] == ["sub-b"]


def test_manual_entry_rejects_anything_that_is_not_a_guid(wizard, monkeypatch, capsys):
    monkeypatch.setattr(cli_ui, "prompt_menu", lambda *a, **k: 4)
    _answers(monkeypatch, "my-subscription", "12345", _GUID_A)

    assert [s["id"] for s in configure.select_subscriptions(list(_SUBS))] == [_GUID_A]
    assert capsys.readouterr().out.count("not a subscription ID") == 2


# ---------------------------------------------------------------------------
# Headless flags
# ---------------------------------------------------------------------------

def test_show_prints_the_current_config_without_writing(wizard, monkeypatch, capsys):
    _forbid_input(monkeypatch)
    utils.save_config({
        "environment": "government",
        "subscriptions": [{"id": _GUID_A, "name": "Alpha"}],
        "default_subscription_id": _GUID_A,
    })

    configure.main(["--show"])

    out = capsys.readouterr().out
    assert "government" in out
    assert _GUID_A in out
    assert "Alpha" in out


def test_validate_lists_visible_subscriptions_and_writes_nothing(wizard, monkeypatch, capsys):
    _forbid_input(monkeypatch)

    configure.main(["--validate"])

    out = capsys.readouterr().out
    assert "Alpha" in out and "Bravo" in out
    assert not wizard.exists()


def test_headless_flags_write_config_without_prompting(wizard, monkeypatch):
    _forbid_input(monkeypatch)
    monkeypatch.setattr(utils, "list_subscriptions", lambda: [
        {"id": _GUID_A, "name": "Alpha", "state": "Enabled", "tenant_id": "t"},
        {"id": _GUID_B, "name": "Bravo", "state": "Enabled", "tenant_id": "t"},
    ])

    configure.main([
        "--environment", "government",
        "--subscriptions", f"{_GUID_A},{_GUID_B}",
        "--default", _GUID_B,
    ])

    saved = json.loads(wizard.read_text(encoding="utf-8"))
    assert saved["environment"] == "government"
    assert [s["id"] for s in saved["subscriptions"]] == [_GUID_A, _GUID_B]
    assert saved["subscriptions"][0]["name"] == "Alpha"
    assert saved["default_subscription_id"] == _GUID_B


def test_headless_subscriptions_all_saves_everything_discovered(wizard, monkeypatch):
    _forbid_input(monkeypatch)

    configure.main(["--subscriptions", "all"])

    saved = json.loads(wizard.read_text(encoding="utf-8"))
    assert [s["id"] for s in saved["subscriptions"]] == ["sub-a", "sub-b"]


def test_headless_environment_auto_is_stored_verbatim(wizard, monkeypatch):
    _forbid_input(monkeypatch)

    configure.main(["--environment", "auto"])

    assert json.loads(wizard.read_text(encoding="utf-8"))["environment"] == "auto"


@pytest.mark.parametrize(
    "argv",
    [
        ["--subscriptions", "not-a-guid"],
        ["--default", "not-a-guid"],
    ],
)
def test_headless_flags_reject_non_guid_subscription_ids(wizard, monkeypatch, capsys, argv):
    _forbid_input(monkeypatch)

    with pytest.raises(SystemExit) as excinfo:
        configure.main(argv)

    assert excinfo.value.code == 2
    assert "not-a-guid" in capsys.readouterr().err
    assert not wizard.exists()


def test_headless_write_survives_unreachable_azure(wizard, monkeypatch):
    _forbid_input(monkeypatch)

    def denied():
        raise utils.AzureAccessError(RuntimeError("offline"), "public")

    monkeypatch.setattr(utils, "list_subscriptions", denied)

    configure.main(["--subscriptions", _GUID_A])

    saved = json.loads(wizard.read_text(encoding="utf-8"))
    assert [s["id"] for s in saved["subscriptions"]] == [_GUID_A]
