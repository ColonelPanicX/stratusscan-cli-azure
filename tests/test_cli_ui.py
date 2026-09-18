"""cli_ui — navigation keys (b/x/q), Ctrl-C/EOF, auto-run short-circuit, invalid input, panels."""

import pytest

import cli_ui


@pytest.fixture(autouse=True)
def interactive(monkeypatch):
    monkeypatch.delenv("STRATUSSCAN_AUTO_RUN", raising=False)


def _answers(monkeypatch, *values):
    """Feed input() one value per call; a value may be an exception to raise."""
    supplied = iter(values)

    def fake_input(prompt=""):
        value = next(supplied)
        if isinstance(value, BaseException):
            raise value
        return value

    monkeypatch.setattr("builtins.input", fake_input)


def test_numbered_choice_returns_int(monkeypatch):
    _answers(monkeypatch, "2")
    assert cli_ui.prompt_menu("T", ["a", "b"]) == 2


def test_b_returns_back(monkeypatch):
    _answers(monkeypatch, "b")
    assert cli_ui.prompt_menu("T", ["a"]) == cli_ui.BACK


def test_x_unwinds_to_the_main_menu(monkeypatch):
    _answers(monkeypatch, "x")
    with pytest.raises(cli_ui.BackToMain):
        cli_ui.prompt_menu("T", ["a"])


def test_q_quits(monkeypatch):
    _answers(monkeypatch, "q")
    with pytest.raises(cli_ui.QuitRequested):
        cli_ui.prompt_menu("T", ["a"])


def test_x_quits_where_there_is_no_main_menu(monkeypatch):
    _answers(monkeypatch, "x")
    with pytest.raises(cli_ui.QuitRequested):
        cli_ui.prompt_menu("T", ["a"], allow_main=False)


@pytest.mark.parametrize("interrupt", [KeyboardInterrupt(), EOFError()])
def test_ctrl_c_and_closed_stdin_quit(monkeypatch, interrupt):
    _answers(monkeypatch, interrupt)
    with pytest.raises(cli_ui.QuitRequested):
        cli_ui.prompt_menu("T", ["a"])


def test_invalid_input_reprompts_until_valid(monkeypatch, capsys):
    _answers(monkeypatch, "9", "", "zz", "1")
    assert cli_ui.prompt_menu("T", ["a"]) == 1
    assert capsys.readouterr().out.count(cli_ui.MSG_INVALID) == 3


def test_disabled_keys_are_not_offered_and_not_accepted(monkeypatch, capsys):
    _answers(monkeypatch, "b", "1")
    assert cli_ui.prompt_menu("T", ["a"], allow_back=False) == 1
    out = capsys.readouterr().out
    assert "b = back" not in out
    assert "x = main menu" in out
    assert "q = quit" in out
    assert cli_ui.MSG_INVALID in out


def test_auto_run_short_circuits_without_prompting(monkeypatch):
    monkeypatch.setenv("STRATUSSCAN_AUTO_RUN", "1")
    monkeypatch.setattr(
        "builtins.input", lambda prompt="": pytest.fail("auto-run must not prompt")
    )
    assert cli_ui.prompt_menu("T", ["a", "b"]) == 1
    assert cli_ui.prompt_confirm("proceed?", default=True) is True


def test_headings_do_not_shift_the_numbering(monkeypatch, capsys):
    _answers(monkeypatch, "3")
    choice = cli_ui.prompt_menu("T", ["a", "b", "c"], headings={1: "First", 3: "Second"})
    out = capsys.readouterr().out
    assert choice == 3
    assert "-- First --" in out and "-- Second --" in out
    assert "  1. a" in out and "  2. b" in out and "  3. c" in out


@pytest.mark.parametrize("answer,expected", [("y", True), ("no", False), ("", True)])
def test_prompt_confirm(monkeypatch, answer, expected):
    _answers(monkeypatch, answer)
    assert cli_ui.prompt_confirm("proceed?", default=True) is expected


def test_prompt_text_quits_on_closed_stdin(monkeypatch):
    _answers(monkeypatch, EOFError())
    with pytest.raises(cli_ui.QuitRequested):
        cli_ui.prompt_text("name: ")


def test_panel_is_a_plain_ascii_box(capsys):
    cli_ui.print_panel("Title", [("Version", "1.2.3"), ("Python", "3.12.9")])
    lines = [line for line in capsys.readouterr().out.splitlines() if line]
    assert lines[0] == "+" + "-" * (cli_ui.PANEL_WIDTH - 2) + "+"
    assert all(len(line) == cli_ui.PANEL_WIDTH for line in lines)
    assert all(line.startswith(("+", "|")) and line.endswith(("+", "|")) for line in lines)
    body = "\n".join(lines)
    assert "Version:" in body and "1.2.3" in body
