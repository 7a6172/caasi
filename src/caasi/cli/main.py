"""Root Typer application for the `caasi` command."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import typer

from .. import __version__, state
from ..i18n import _
from . import (
    benchmark_cmd,
    config_cmd,
    container_cmd,
    control_cmd,
    dataset_cmd,
    gpu,
    lab,
    misc,
    moveit_cmd,
    native_cmd,
    nav_cmd,
    project_cmd,
    remote_cmd,
    replay_cmd,
    ros_cmd,
    run_cmd,
    sensor_cmd,
    setup_cmd,
    shell_cmd,
    sim,
    train_cmd,
    view_cmd,
    vision_cmd,
)
from . import system as system_cmd
from .definitions import build_app
from .doctor import doctor_command
from .init_cmd import init_command

app = typer.Typer(
    name="caasi",
    help=_("cli.help"),
    no_args_is_help=True,
    add_completion=True,
    rich_markup_mode="rich",
    context_settings={"help_option_names": ["-h", "--help"]},
)


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(f"caasi {__version__}")
        raise typer.Exit()


@app.callback()
def root(
    verbose: bool = typer.Option(False, "--verbose", "-v", help=_("cli.flag.verbose")),
    quiet: bool = typer.Option(False, "--quiet", "-q", help=_("cli.flag.quiet")),
    json_output: bool = typer.Option(False, "--json", help=_("cli.flag.json")),
    config: Optional[Path] = typer.Option(None, "--config", help=_("cli.flag.config")),
    lang: Optional[str] = typer.Option(None, "--lang", help=_("cli.flag.lang")),
    version: Optional[bool] = typer.Option(
        None,
        "--version",
        callback=_version_callback,
        is_eager=True,
        help=_("cli.flag.version"),
    ),
) -> None:
    """Store global options, load configuration and resolve the locale."""
    state.configure(
        verbose=verbose,
        quiet=quiet,
        json_output=json_output,
        config_path=config,
        lang=lang,
    )


app.command("version", help=_("version.help"))(misc.version_command)
app.command("info", help=_("info.help"))(misc.info_command)
app.command("doctor", help=_("doctor.help"))(doctor_command)
app.add_typer(gpu.app, name="gpu", help=_("gpu.help"))
app.add_typer(system_cmd.app, name="system", help=_("system.help"))
app.add_typer(config_cmd.app, name="config", help=_("config.help"))
app.add_typer(sim.app, name="sim", help=_("sim.help"))
app.add_typer(lab.app, name="lab", help=_("lab.help"))
app.add_typer(run_cmd.app, name="run", help=_("run.help"))
app.command("logs", help=_("logs.help"))(run_cmd.run_logs)
app.command("init", help=_("init.help"))(init_command)
app.command("setup", help=_("setup.help"))(setup_cmd.setup_command)
app.add_typer(project_cmd.app, name="project", help=_("project.help"))
app.add_typer(build_app("robot"), name="robot", help=_("robot.help"))
app.add_typer(build_app("scene"), name="scene", help=_("scene.help"))
app.add_typer(build_app("task"), name="task", help=_("task.help"))
app.command(
    "train",
    help=_("train.help"),
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
)(train_cmd.train_command)
app.add_typer(benchmark_cmd.app, name="benchmark", help=_("benchmark.help"))
app.add_typer(dataset_cmd.app, name="dataset", help=_("dataset.help"))
app.command("replay", help=_("replay.help"))(replay_cmd.replay_command)
app.add_typer(native_cmd.app, name="native", help=_("native.help"))
app.command("shell", help=_("shell.help"))(shell_cmd.shell_command)
app.add_typer(sensor_cmd.app, name="sensor", help=_("sensor.help"))
app.add_typer(view_cmd.app, name="view", help=_("view.help"))
app.add_typer(vision_cmd.app, name="vision", help=_("vision.help"))
app.add_typer(ros_cmd.app, name="ros", help=_("ros.help"))
app.add_typer(nav_cmd.app, name="nav", help=_("nav.help"))
app.add_typer(moveit_cmd.app, name="moveit", help=_("moveit.help"))
app.add_typer(control_cmd.app, name="control", help=_("control.help"))
app.add_typer(remote_cmd.app, name="remote", help=_("remote.help"))
app.add_typer(container_cmd.app, name="container", help=_("container.help"))


def run() -> None:
    """Console script entry point (`caasi`)."""
    app()


if __name__ == "__main__":  # pragma: no cover
    run()
