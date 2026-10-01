"""`caasi lab` — run, play and evaluate Isaac Lab experiments.

The launch verbs are domain doors onto the canonical launcher (§5.4):
they delegate to :func:`caasi.cli.run_cmd.launch_experiment` so every
started run gets the §4.7 provenance bundle.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Optional

import typer

from .. import state
from ..checks.isaac import detect_isaac_lab
from ..core import experiment
from ..i18n import _
from ..utils import output, shell
from . import run_cmd

app = typer.Typer(no_args_is_help=True)

_PASS_THROUGH = {"allow_extra_args": True, "ignore_unknown_options": True}


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


def _script_for(exp: experiment.Experiment, *keys: str) -> experiment.Experiment:
    """Swap in an alternative script declared in the config (first key wins)."""
    for key in keys:
        value = exp.raw.get(key)
        if value:
            return replace(exp, script=str(value))
    return exp


def _checkpoint_args(checkpoint: Optional[Path], passthrough: list[str]) -> list[str]:
    if checkpoint is not None:
        return ["--checkpoint", str(checkpoint), *passthrough]
    return passthrough


@app.command("run", help=_("lab.run_help"), context_settings=_PASS_THROUGH)
def lab_run(
    ctx: typer.Context,
    config_path: Path = typer.Argument(..., help=_("sim.run.config_help")),
    name: Optional[str] = typer.Option(None, "--name", help=_("sim.run.name_help")),
    dry_run: bool = typer.Option(False, "--dry-run", help=_("sim.run.dry_run_help")),
    json_output: bool = typer.Option(False, "--json", help=_("flag.json")),
) -> None:
    run_cmd.launch_experiment(
        config_path,
        expect_backend="lab",
        name=name,
        kind="experiment",
        extra_args=list(ctx.args),
        dry_run=dry_run,
        json_output=json_output,
    )


@app.command("play", help=_("lab.play_help"), context_settings=_PASS_THROUGH)
def lab_play(
    ctx: typer.Context,
    config_path: Path = typer.Argument(..., help=_("sim.run.config_help")),
    checkpoint: Optional[Path] = typer.Option(None, "--checkpoint", help=_("lab.flag.checkpoint")),
    name: Optional[str] = typer.Option(None, "--name", help=_("sim.run.name_help")),
    dry_run: bool = typer.Option(False, "--dry-run", help=_("sim.run.dry_run_help")),
    json_output: bool = typer.Option(False, "--json", help=_("flag.json")),
) -> None:
    run_cmd.launch_experiment(
        config_path,
        expect_backend="lab",
        name=name,
        kind="play",
        extra_args=_checkpoint_args(checkpoint, list(ctx.args)),
        extra={"checkpoint": str(checkpoint) if checkpoint else None},
        dry_run=dry_run,
        json_output=json_output,
        transform=lambda exp: _script_for(exp, "play_script"),
    )


@app.command("evaluate", help=_("lab.evaluate_help"), context_settings=_PASS_THROUGH)
def lab_evaluate(
    ctx: typer.Context,
    config_path: Path = typer.Argument(..., help=_("sim.run.config_help")),
    checkpoint: Optional[Path] = typer.Option(None, "--checkpoint", help=_("lab.flag.checkpoint")),
    name: Optional[str] = typer.Option(None, "--name", help=_("sim.run.name_help")),
    dry_run: bool = typer.Option(False, "--dry-run", help=_("sim.run.dry_run_help")),
    json_output: bool = typer.Option(False, "--json", help=_("flag.json")),
) -> None:
    run_cmd.launch_experiment(
        config_path,
        expect_backend="lab",
        name=name,
        kind="evaluate",
        extra_args=_checkpoint_args(checkpoint, list(ctx.args)),
        extra={"checkpoint": str(checkpoint) if checkpoint else None},
        dry_run=dry_run,
        json_output=json_output,
        transform=lambda exp: _script_for(exp, "evaluate_script", "play_script"),
    )
