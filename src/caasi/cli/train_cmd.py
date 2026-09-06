"""`caasi train` — train policies headlessly (Isaac Lab + PyTorch).

Training is launched as a tracked background run; follow it with
`caasi logs <run> -f` and manage it with `caasi run ...`.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import typer

from .. import state
from ..core import experiment, runs
from ..i18n import _
from ..utils import output


def build_training_args(
    *,
    steps: int | None,
    envs: int | None,
    resume: Path | None,
    seed: int | None,
    device: str | None,
    headless: bool,
    extra: list[str] | None = None,
) -> list[str]:
    """Translate CLI flags into script arguments (pass-through convention)."""
    args: list[str] = []
    if steps is not None:
        args += ["--steps", str(steps)]
    if envs is not None:
        args += ["--envs", str(envs)]
    if resume is not None:
        args += ["--resume", str(resume)]
    if seed is not None:
        args += ["--seed", str(seed)]
    if device:
        args += ["--device", device]
    if headless:
        args.append("--headless")
    return [*args, *(extra or [])]


def train_command(
    ctx: typer.Context,
    config_path: Path = typer.Argument(..., help=_("train.arg.config")),
    steps: Optional[int] = typer.Option(None, "--steps", help=_("train.flag.steps")),
    envs: Optional[int] = typer.Option(None, "--envs", help=_("train.flag.envs")),
    resume: Optional[Path] = typer.Option(None, "--resume", help=_("train.flag.resume")),
    seed: Optional[int] = typer.Option(None, "--seed", help=_("train.flag.seed")),
    device: Optional[str] = typer.Option(None, "--device", help=_("train.flag.device")),
    dry_run: bool = typer.Option(False, "--dry-run", help=_("train.flag.dry_run")),
) -> None:
    cfg = state.cfg()
    try:
        exp = experiment.load_experiment(config_path)
    except experiment.ExperimentError as exc:
        output.fail(str(exc))
        return
    extra_args = build_training_args(
        steps=steps, envs=envs, resume=resume, seed=seed, device=device,
        headless=exp.headless, extra=list(ctx.args),
    )
    try:
        command, env = experiment.build_command(exp, cfg, extra_args=extra_args)
    except experiment.ExperimentError as exc:
        output.fail(str(exc))
        return

    if dry_run:
        output.echo(f"[bold]{_('sim.run.dry_title')}[/bold]")
        output.echo(f"  command: {' '.join(command)}")
        output.echo(f"  cwd:     {exp.work_dir}")
        return

    record = runs.start_run(
        cfg,
        name=exp.name,
        command=command,
        cwd=exp.work_dir,
        env=env,
        backend=exp.backend,
        kind="train",
        extra={
            "experiment": str(exp.config_path),
            "steps": steps,
            "envs": envs,
        },
    )
    output.echo(f"[green]{_('sim.run.started', id=record.run_id)}[/green]")
    output.echo(f"  [dim]{_('sim.run.watch', id=record.run_id)}[/dim]")
