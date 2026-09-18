#!/usr/bin/env python3
"""
StratusScanCLI-Azure — Console UI

Every interactive prompt and every framed panel the tool prints lives here.
utils.py is the library the exporters import, so it stays print-free and
input-free; the menu code that used to sit there moved to this module.

Navigation is the tool-wide standard, shared with StratusScanCLI-AWS:
    b = back        return to the parent menu
    x = main menu   unwind out of any nested menu (BackToMain)
    q = quit        leave the tool (QuitRequested)

Ctrl-C or a closed stdin at any prompt is treated as quit.
"""

import sys

import utils


class BackToMain(Exception):  # noqa: N818 — a navigation signal, not an error
    """The user asked to unwind to the main menu ('x')."""


class QuitRequested(Exception):  # noqa: N818 — a navigation signal, not an error
    """The user asked to leave the tool ('q', Ctrl-C or EOF)."""


BACK = "back"

MSG_INVALID = "Invalid choice. Please try again."

PANEL_WIDTH = 64


def _nav_footer(allow_back: bool, allow_main: bool, allow_quit: bool) -> str:
    parts = []
    if allow_back:
        parts.append("b = back")
    if allow_main:
        parts.append("x = main menu")
    if allow_quit:
        parts.append("q = quit")
    return "  " + "  |  ".join(parts)


def prompt_menu(
    title: str,
    options: list[str],
    allow_back: bool = True,
    allow_main: bool = True,
    allow_quit: bool = True,
    headings: dict[int, str] | None = None,
) -> int | str:
    """
    Display a numbered menu and return the user's choice.

    headings maps a 1-based option number to a category heading printed above
    that option; numbering stays continuous across the headings.

    In auto-run mode, returns 1 without prompting.

    Returns:
        int 1..N for a numbered choice, or BACK ('back') for 'b'.

    Raises:
        BackToMain: the user entered 'x' and allow_main is set. Where there is
            no main menu to return to (configure.py), 'x' is an alias for quit.
        QuitRequested: the user entered 'q', pressed Ctrl-C, or stdin is closed.
    """
    if utils.is_auto_run():
        return 1

    print(f"\n{title}")
    print("=" * PANEL_WIDTH)
    for i, opt in enumerate(options, 1):
        heading = (headings or {}).get(i)
        if heading:
            print(f"\n  -- {heading} --")
        print(f"  {i}. {opt}")
    print("-" * PANEL_WIDTH)
    if allow_back or allow_main or allow_quit:
        print(_nav_footer(allow_back, allow_main, allow_quit))
    print("=" * PANEL_WIDTH)

    valid = {str(i) for i in range(1, len(options) + 1)}
    if allow_back:
        valid.add("b")
    if allow_main or allow_quit:
        valid.add("x")
    if allow_quit:
        valid.add("q")

    while True:
        try:
            choice = input("Enter your choice: ").strip().lower()
        except (KeyboardInterrupt, EOFError):
            print()
            raise QuitRequested from None
        if choice in valid:
            if choice == "b":
                return BACK
            if choice == "x":
                if allow_main:
                    raise BackToMain
                raise QuitRequested
            if choice == "q":
                raise QuitRequested
            return int(choice)
        print(MSG_INVALID)


def prompt_text(prompt: str) -> str:
    """Read one line. Ctrl-C or a closed stdin is quit, as at any other prompt."""
    try:
        return input(prompt).strip()
    except (KeyboardInterrupt, EOFError):
        print()
        raise QuitRequested from None


def prompt_confirm(question: str, default: bool = False) -> bool:
    """Ask a yes/no question. In auto-run mode, returns default without prompting."""
    if utils.is_auto_run():
        return default
    suffix = "[Y/n]" if default else "[y/N]"
    while True:
        answer = prompt_text(f"{question} {suffix}: ").lower()
        if not answer:
            return default
        if answer in ("y", "yes"):
            return True
        if answer in ("n", "no"):
            return False
        print(MSG_INVALID)


def _panel_row(text: str, width: int) -> str:
    inner = width - 4
    if len(text) > inner:
        text = text[: inner - 3] + "..."
    return "| " + text.ljust(inner) + " |"


def print_panel(
    title: str,
    rows: list[tuple[str, str]],
    width: int = PANEL_WIDTH,
    stream=None,
) -> None:
    """Print a plain ASCII box: a title line, a rule, then aligned label/value rows."""
    out = stream or sys.stdout
    rule = "+" + "-" * (width - 2) + "+"
    label_width = max((len(label) for label, _ in rows), default=0) + 2
    print("", file=out)
    print(rule, file=out)
    print(_panel_row(title, width), file=out)
    print(rule, file=out)
    for label, value in rows:
        print(_panel_row(f"{label + ':':<{label_width}}{value}", width), file=out)
    print(rule, file=out)
