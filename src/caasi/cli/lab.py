"""`caasi lab` — run, train and evaluate Isaac Lab experiments."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Optional

import typer

from .. import state
from ..checks.isaac import detect_isaac_lab
from ..core import experiment, runs
from ..i18n import _
from ..utils import output, shell
from .train_cmd import build_training_args

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


def _load(config_path: Path, json_output: bool) -> experiment.Experiment | None:
    try:
        exp = experiment.load_experiment(config_path)
    except experiment.ExperimentError as exc:
        output.fail(str(exc))
        return None
    if exp.backend != "lab" and not output.wants_json(json_output):
        output.echo(f"[yellow]{_('lab.run.backend_note', backend=exp.backend)}[/yellow]")
    return exp


def _launch(
    exp: experiment.Experiment,
    *,
    extra_args: list[str],
    kind: str,
    name: Optional[str],
    dry_run: bool,
    json_output: bool,
    extra: dict,
) -> None:
    try:
        command, env = experiment.build_command(exp, state.cfg(), extra_args=extra_args)
    except experiment.ExperimentError as exc:
        output.fail(str(exc))
        return

    if dry_run:
        output.echo(f"[bold]{_('sim.run.dry_title')}[/bold]")
        output.echo(f"  command: {' '.join(command)}")
        output.echo(f"  cwd:     {exp.work_dir}")
        return

    record = runs.start_run(
        state.cfg(),
        name=name or exp.name,
        command=command,
        cwd=exp.work_dir,
        env=env,
        backend=exp.backend,
        kind=kind,
        extra={"experiment": str(exp.config_path), **extra},
    )
    if output.wants_json(json_output):
        output.echo_json(record.to_dict())
        return
    output.echo(f"[green]{_('sim.run.started', id=record.run_id)}[/green]")
    output.echo(f"  [dim]{_('sim.run.watch', id=record.run_id)}[/dim]")


def _script_for(exp: experiment.Experiment, *keys: str) -> experiment.Experiment:
    """Swap in an alternative script declared in the config (first key wins)."""
    for key in keys:
        value = exp.raw.get(key)
        if value:
            return replace(exp, script=str(value))
    return exp


@app.command("run", help=_("lab.run_help"), context_settings=_PASS_THROUGH)
def lab_run(
    ctx: typer.Context,
    config_path: Path = typer.Argument(..., help=_("sim.run.config_help")),
    name: Optional[str] = typer.Option(None, "--name", help=_("sim.run.name_help")),
    dry_run: bool = typer.Option(False, "--dry-run", help=_("sim.run.dry_run_help")),
    json_output: bool = typer.Option(False, "--json", help=_("flag.json")),
) -> None:
    exp = _load(config_path, json_output)
    if exp is None:
        return
    _launch(
        exp,
        extra_args=list(ctx.args),
        kind="experiment",
        name=name,
        dry_run=dry_run,
        json_output=json_output,
        extra={"headless": exp.headless},
    )


@app.command("train", help=_("lab.train_help"), context_settings=_PASS_THROUGH)
def lab_train(
    ctx: typer.Context,
    config_path: Path = typer.Argument(..., help=_("train.arg.config")),
    steps: Optional[int] = typer.Option(None, "--steps", help=_("train.flag.steps")),
    envs: Optional[int] = typer.Option(None, "--envs", help=_("train.flag.envs")),
    resume: Optional[Path] = typer.Option(None, "--resume", help=_("train.flag.resume")),
    seed: Optional[int] = typer.Option(None, "--seed", help=_("train.flag.seed")),
    device: Optional[str] = typer.Option(None, "--device", help=_("train.flag.device")),
    name: Optional[str] = typer.Option(None, "--name", help=_("sim.run.name_help")),
    dry_run: bool = typer.Option(False, "--dry-run", help=_("train.flag.dry_run")),
    json_output: bool = typer.Option(False, "--json", help=_("flag.json")),
) -> None:
    exp = _load(config_path, json_output)
    if exp is None:
        return
    extra_args = build_training_args(
        steps=steps, envs=envs, resume=resume, seed=seed, device=device,
        headless=exp.headless, extra=list(ctx.args),
    )
    _launch(
        exp,
        extra_args=extra_args,
        kind="train",
        name=name,
        dry_run=dry_run,
        json_output=json_output,
        extra={"steps": steps, "envs": envs},
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
    exp = _load(config_path, json_output)
    if exp is None:
        return
    exp = _script_for(exp, "play_script")
    extra_args = list(ctx.args)
    if checkpoint is not None:
        extra_args = ["--checkpoint", str(checkpoint), *extra_args]
    _launch(
        exp,
        extra_args=extra_args,
        kind="play",
        name=name,
        dry_run=dry_run,
        json_output=json_output,
        extra={"checkpoint": str(checkpoint) if checkpoint else None},
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
    exp = _load(config_path, json_output)
    if exp is None:
        return
    exp = _script_for(exp, "evaluate_script", "play_script")
    extra_args = list(ctx.args)
    if checkpoint is not None:
        extra_args = ["--checkpoint", str(checkpoint), *extra_args]
    _launch(
        exp,
        extra_args=extra_args,
        kind="evaluate",
        name=name,
        dry_run=dry_run,
        json_output=json_output,
        extra={"checkpoint": str(checkpoint) if checkpoint else None},
    )
