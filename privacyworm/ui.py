"""Tiny terminal UI helpers shared by the guided flow and the CLI.

Plain ``input()`` underneath (so tests can feed answers through stdin)
with a little colour on top. Colour switches off automatically when
output isn't a terminal or ``NO_COLOR`` is set.
"""

from __future__ import annotations

import os
import sys
import textwrap

import click

WIDTH = 72


def _color() -> bool:
    return sys.stdout.isatty() and not os.environ.get("NO_COLOR")


def style(text: str, **kw) -> str:
    return click.style(text, **kw) if _color() else text


def say(text: str = "", indent: int = 0) -> None:
    pad = " " * indent
    for line in text.split("\n"):
        click.echo(pad + line if line else "")


def para(text: str, indent: int = 2) -> None:
    """Print a wrapped paragraph."""
    wrapped = textwrap.fill(" ".join(text.split()), width=WIDTH - indent)
    say(wrapped, indent=indent)


def title(text: str) -> None:
    click.echo()
    click.echo(style(text, bold=True))
    click.echo(style("─" * min(len(text), WIDTH), dim=True))


def good(text: str) -> None:
    click.echo(style("  ✓ ", fg="green", bold=True) + text)


def warn(text: str) -> None:
    click.echo(style("  ! ", fg="yellow", bold=True) + text)


def bad(text: str) -> None:
    click.echo(style("  ✗ ", fg="red", bold=True) + text)


def dim(text: str) -> None:
    click.echo(style(text, dim=True))


def ask(prompt: str, default: str = "") -> str:
    """Free-text question. Returns default on Enter or end-of-input."""
    hint = f" [{default}]" if default else ""
    try:
        answer = input(style(f"  {prompt}{hint}: ", bold=True)).strip()
    except EOFError:
        click.echo()
        return default
    return answer or default


def yes_no(prompt: str, default: bool = True) -> bool:
    hint = "Y/n" if default else "y/N"
    while True:
        try:
            answer = input(style(f"  {prompt} [{hint}]: ", bold=True)).strip().lower()
        except EOFError:
            click.echo()
            return default
        if not answer:
            return default
        if answer in ("y", "yes"):
            return True
        if answer in ("n", "no"):
            return False
        say("  Please type y or n.")


def choose(prompt: str, options: list[tuple[str, str]], default: str | None = None) -> str:
    """Show a short menu and return the chosen key.

    ``options`` is a list of (key, label). Keys are what the user types.
    End-of-input returns ``default`` or the last option (usually quit).
    """
    for key, label in options:
        click.echo(f"    {style(key, fg='cyan', bold=True)}  {label}")
    keys = {k.lower() for k, _ in options}
    hint = f" [{default}]" if default else ""
    while True:
        try:
            answer = input(style(f"  {prompt}{hint}: ", bold=True)).strip().lower()
        except EOFError:
            click.echo()
            return default or options[-1][0]
        if not answer and default:
            return default
        if answer in keys:
            return answer
        say(f"  Type one of: {', '.join(k for k, _ in options)}")


def pause(prompt: str = "Press Enter to continue") -> None:
    try:
        input(style(f"  {prompt}... ", dim=True))
    except EOFError:
        click.echo()


def interactive() -> bool:
    """True when a person is at the keyboard."""
    try:
        return sys.stdin.isatty()
    except (AttributeError, ValueError):
        return False
