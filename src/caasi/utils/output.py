"""Output helpers: Rich console, JSON emission, status symbols, exit helpers."""

from __future__ import annotations

import json as _jsonlib
from typing import Any

import typer
from rich.console import Console

from .. import state
from ..i18n import _

_console: Console | None = None
_err_console: Console | None = None

# status -> (symbol, rich style)
STATUS_STYLE: dict[str, tuple[str, str]] = {
    "ok": ("✓", "green"),
    "warn": ("!", "yellow"),
    "fail": ("✗", "red"),
    "skip": ("•", "dim"),
}


def console() -> Console:
    global _console
    if _console is None:
        _console = Console()
    return _console


def err_console() -> Console:
    global _err_console
    if _err_console is None:
        _err_console = Console(stderr=True)
    return _err_console


def status_symbol(status: str) -> tuple[str, str]:
    return STATUS_STYLE.get(status, ("?", "white"))


def echo(message: str = "", **kwargs: Any) -> None:
    """Print a human-readable message unless --quiet is active."""
    if state.get().quiet:
        return
    console().print(message, **kwargs)


def echo_json(data: Any) -> None:
    """Print machine-readable JSON (always printed, even with --quiet)."""
    print(_jsonlib.dumps(data, indent=2, default=str))


def wants_json(local_flag: bool = False) -> bool:
    """True when output should be JSON (local --json or global --json)."""
    return local_flag or state.get().json_output


def fail(message: str, exit_code: int = 1) -> None:
    """Print an error to stderr and exit with the given code (default 1)."""
    typer.secho(_("common.error", message=message), err=True, fg=typer.colors.RED)
    raise typer.Exit(exit_code)
