"""`caasi teleop` — drive a robot, record demonstrations, replay bags.

Every command delegates: ``start`` launches the resolved teleop stack from
the ``teleop`` catalog domain (or an experiment YAML carrying the robot's
sim), ``record``/``replay`` are ``ros2 bag record``/``play``, and ``stop``
reuses :func:`caasi.core.runs.stop_run`. Recordings land in ``datasets/``
with ``metadata.json``, so the ``plan3.md`` §25 workflow holds:
``teleop record`` → ``dataset inspect`` → ``lab train`` → ``lab evaluate``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import typer

from .. import state
from ..core import dataset as dataset_core, experiment, runs, teleop
from ..core import ros as ros_core
from ..i18n import _
from ..utils import output

app = typer.Typer(no_args_is_help=True)

#: Native pass-through [X]: unknown flags go to the delegated tool.
_EXTRA_SETTINGS = {"allow_extra_args": True, "ignore_unknown_options": True}


@app.command(
    "start",
    help=_("teleop.start_help"),
    context_settings=_EXTRA_SETTINGS,
)
def teleop_start(
    ctx: typer.Context,
    args: Optional[list[str]] = typer.Argument(None, help=_("teleop.arg.config")),
    backend: Optional[str] = typer.Option(
        None, "--backend", "-b", help=_("ecosystem.flag.backend", domain="teleop")
    ),
    device: Optional[str] = typer.Option(None, "--device", help=_("teleop.flag.device")),
    name: Optional[str] = typer.Option(None, "--name", help=_("ecosystem.flag.name")),
    dry_run: bool = typer.Option(False, "--dry-run", help=_("teleop.flag.dry_run")),
) -> None:
    cfg = state.cfg()
    tokens = [str(token) for token in (args or [])]
    config: Path | None = None
    if tokens and tokens[0].lower().endswith((".yaml", ".yml")):
        config = Path(tokens[0]).expanduser()
        tokens = tokens[1:]
    extra = [*tokens, *(str(a) for a in ctx.args)]

    if config is not None:
        # §25: an experiment YAML launches the robot's sim as the teleop run.
        try:
            exp = experiment.load_experiment(config)
            command, env = experiment.build_command(exp, cfg, extra_args=extra)
        except experiment.ExperimentError as exc:
            output.fail(str(exc))
            return
        run_name = name or exp.name
        run_backend = exp.backend
        cwd: str | Path | None = exp.work_dir
        run_extra: dict = {"experiment": str(exp.config_path)}
    else:
        try:
            item = teleop.pick_backend(cfg, backend)
            command, env = teleop.stack_command(item, cfg, device=device, extra=extra)
        except (teleop.TeleopError, ros_core.RosError) as exc:
            output.fail(str(exc))
            return
        run_name = name or item.capability.key
        run_backend = "ros" if item.launch else (item.capability.tool or "script")
        cwd = None
        run_extra = {"domain": teleop.DOMAIN, "capability": item.capability.key}

    if dry_run:
        output.echo(f"[bold]{_('sim.run.dry_title')}[/bold]")
        output.echo(f"  command: {' '.join(str(part) for part in command)}")
        return

    record = runs.start_run(
        cfg,
        name=run_name,
        command=command,
        cwd=cwd,
        env=env or None,
        backend=run_backend,
        kind="teleop",
        extra=run_extra,
    )
    output.echo(f"[green]{_('teleop.started', id=record.run_id)}[/green]")
    output.echo(f"  [dim]{_('sim.run.watch', id=record.run_id)}[/dim]")


@app.command(
    "record",
    help=_("teleop.record_help"),
    context_settings=_EXTRA_SETTINGS,
)
def teleop_record(
    ctx: typer.Context,
    topics: Optional[list[str]] = typer.Option(
        None, "--topics", "-t", help=_("teleop.flag.topics")
    ),
    name: Optional[str] = typer.Option(None, "--name", help=_("teleop.flag.name")),
    dry_run: bool = typer.Option(False, "--dry-run", help=_("teleop.flag.dry_run")),
) -> None:
    cfg = state.cfg()
    try:
        binary = ros_core.require_ros2()
    except ros_core.RosError as exc:
        output.fail(str(exc))
        return
    label = name or "teleop"
    dest = dataset_core.new_dataset_dir(dataset_core.datasets_base(cfg), label)
    recorded = [str(topic) for topic in (topics or [])] or ["-a"]
    command = teleop.record_command(binary, recorded, dest, [str(a) for a in ctx.args])
    env = teleop.launch_env()

    if dry_run:
        output.echo(f"[bold]{_('sim.run.dry_title')}[/bold]")
        output.echo(f"  command: {' '.join(command)}")
        output.echo(f"  dest:    {dest}")
        return

    dest.mkdir(parents=True, exist_ok=True)
    record = runs.start_run(
        cfg,
        name=label,
        command=command,
        env=env,
        backend="ros2",
        kind="bag",
        extra={"topics": recorded, "dataset": str(dest)},
    )
    dataset_core.write_metadata(
        dest, teleop.record_metadata(label, record.created, record.run_id, recorded)
    )
    output.echo(f"[green]{_('teleop.recording', path=str(dest))}[/green]")
    output.echo(f"  [dim]{_('sim.run.watch', id=record.run_id)}[/dim]")


@app.command("stop", help=_("teleop.stop_help"))
def teleop_stop() -> None:
    cfg = state.cfg()
    active = teleop.active_runs(cfg)
    if not active:
        output.echo(f"[dim]{_('teleop.no_active')}[/dim]")
        return
    for record in active:
        runs.stop_run(record)
        output.echo(
            f"[green]{_('teleop.stopped_run', id=record.run_id, kind=record.kind)}[/green]"
        )


@app.command(
    "replay",
    help=_("teleop.replay_help"),
    context_settings=_EXTRA_SETTINGS,
)
def teleop_replay(
    ctx: typer.Context,
    bag: Path = typer.Argument(..., help=_("teleop.arg.bag")),
    dry_run: bool = typer.Option(False, "--dry-run", help=_("teleop.flag.dry_run")),
) -> None:
    cfg = state.cfg()
    source = bag.expanduser()
    if not source.exists():
        output.fail(_("teleop.no_bag", path=str(source)))
        return
    try:
        binary = ros_core.require_ros2()
    except ros_core.RosError as exc:
        output.fail(str(exc))
        return
    command = teleop.play_command(binary, source, [str(a) for a in ctx.args])
    env = teleop.launch_env()

    if dry_run:
        output.echo(f"[bold]{_('sim.run.dry_title')}[/bold]")
        output.echo(f"  command: {' '.join(command)}")
        return

    record = runs.start_run(
        cfg,
        name=source.name,
        command=command,
        env=env,
        backend="ros2",
        kind="replay",
        extra={"bag": str(source)},
    )
    output.echo(f"[green]{_('teleop.replay_started', path=str(source))}[/green]")
    output.echo(f"  [dim]{_('sim.run.watch', id=record.run_id)}[/dim]")
