"""Output helpers: Rich console, JSON emission, status symbols, exit helpers."""

from __future__ import annotations

import json as _jsonlib
import os
from typing import Any

import typer
from rich.console import Console
from rich.text import Text

from .. import state
from ..i18n import _

_console: Console | None = None
_err_console: Console | None = None
_console_color: str | None = None

# status -> (symbol, rich style)
STATUS_STYLE: dict[str, tuple[str, str]] = {
    "ok": ("✓", "green"),
    "warn": ("!", "yellow"),
    "fail": ("✗", "red"),
    "skip": ("•", "dim"),
}

LAYOUTS = ("rich", "plain")
DEFAULT_LAYOUT = "rich"
ENV_LAYOUT = "CAASI_LAYOUT"


def resolve_layout(cli_layout: str | None = None, config_layout: str | None = None) -> str:
    """Resolve the effective layout from flag > env > config > default."""
    for candidate in (cli_layout, os.environ.get(ENV_LAYOUT), config_layout):
        if candidate in LAYOUTS:
            return candidate
    return DEFAULT_LAYOUT


def layout() -> str:
    """The active table layout, resolved against the loaded configuration."""
    return resolve_layout(state.get().layout, state.cfg().layout)


def table_styles() -> dict[str, Any]:
    """`rich.table.Table` kwargs for the active layout.

    ``plain`` gives space-aligned columns; ``rich`` returns nothing so that
    rich's own defaults (bordered box, padded edges) apply.
    """
    if layout() == "plain":
        return {"box": None, "pad_edge": False}
    return {}


HELP_ORDERS = ("grouped", "core", "alpha")
DEFAULT_HELP_ORDER = "grouped"
ENV_HELP_ORDER = "CAASI_HELP_ORDER"


def resolve_help_order(config_order: str | None = None) -> str:
    """Resolve the root help listing order from env > config > default.

    There is no flag: ``--help`` is eager and exits before the root callback
    stores anything, so only render-time sources can reach it.
    """
    for candidate in (os.environ.get(ENV_HELP_ORDER), config_order):
        if candidate in HELP_ORDERS:
            return candidate
    return DEFAULT_HELP_ORDER


def help_order() -> str:
    """The active root help order, resolved against the loaded configuration."""
    return resolve_help_order(state.cfg().help_order)


def _build_console(mode: str, stderr: bool) -> Console:
    """Console for the requested --color mode; 'auto' keeps rich's detection (TTY + NO_COLOR)."""
    if mode == "always":
        return Console(stderr=stderr, force_terminal=True)
    if mode == "never":
        return Console(stderr=stderr, no_color=True)
    return Console(stderr=stderr)


def _consoles() -> tuple[Console, Console]:
    global _console, _err_console, _console_color
    mode = state.get().color or "auto"
    if _console is None or _err_console is None or mode != _console_color:
        _console = _build_console(mode, stderr=False)
        _err_console = _build_console(mode, stderr=True)
        _console_color = mode
    return _console, _err_console


def console() -> Console:
    return _consoles()[0]


def err_console() -> Console:
    return _consoles()[1]


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
    err_console().print(Text(_("common.error", message=message), style="red"))
    raise typer.Exit(exit_code)
