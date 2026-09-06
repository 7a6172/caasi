"""`caasi lab` — inspect the Isaac Lab environment."""

from __future__ import annotations

import typer

from .. import state
from ..checks.isaac import detect_isaac_lab
from ..i18n import _
from ..utils import output, shell

app = typer.Typer(no_args_is_help=True)


@app.command("status", help=_("lab.status_help"))
def lab_status(json_output: bool = typer.Option(False, "--json", help=_("flag.json"))) -> None:
    cfg = state.cfg()
    status, detail, hint = detect_isaac_lab(cfg)
    resolved = cfg.resolve_tool("isaaclab")

    launcher = None
    if resolved and resolved.expanded_path:
        candidate = resolved.expanded_path / "isaaclab.sh"
        if candidate.is_file():
            launcher = str(candidate)

    payload = {
        "status": status,
        "detail": detail,
        "version": resolved.version if resolved else None,
        "path": resolved.path if resolved else None,
        "python": resolved.python if resolved else None,
        "launcher": launcher,
        "ros2_bridge": bool(shell.which("ros2")),
    }
    if output.wants_json(json_output):
        output.echo_json(payload)
        return

    symbol, style = output.status_symbol(status)
    output.echo(f"[{style}]{symbol}[/] {detail}")
    if launcher:
        output.echo(f"  Launcher: {launcher}")
    if resolved and resolved.python:
        output.echo(f"  Python:   {resolved.python}")
    if status == "fail" and hint:
        output.echo(f"  [dim]↳ {hint}[/dim]")
