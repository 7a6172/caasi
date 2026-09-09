"""Root Typer application for the `caasi` command."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Optional

import typer
from typer.core import TyperGroup

from .. import __version__, state
from ..i18n import _
from ..utils import output
from . import (
    accelerated,
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
    synth_cmd,
    teleop_cmd,
    train_cmd,
    view_cmd,
    vision_cmd,
)
from . import platform as platform_cmd
from . import system as system_cmd
from .definitions import build_app
from .doctor import doctor_command
from .init_cmd import init_command

if TYPE_CHECKING:  # pragma: no cover
    # Typer >= 0.27 vendors Click as `typer._click` and does not install `click`.
    from typer._click import Context, HelpFormatter

# Root help taxonomy: panel title -> commands, alphabetical within each panel.
# Mirrors the group table in README.md and the command map in docs/.
HELP_PANELS: dict[str, tuple[str, ...]] = {
    _("help.panel.start"): ("doctor", "help", "info", "init", "setup", "version"),
    _("help.panel.environment"): ("config", "gpu", "sensor", "system", "vision"),
    _("help.panel.projects"): (
        "logs",
        "project",
        "replay",
        "robot",
        "run",
        "scene",
        "task",
        "view",
    ),
    _("help.panel.simulation"): ("benchmark", "lab", "physics", "sim", "train"),
    _("help.panel.data"): ("dataset", "synth", "teleop"),
    _("help.panel.ros"): ("control", "moveit", "nav", "ros"),
    _("help.panel.accelerated"): (
        "isaac-ros",
        "mapping",
        "motion",
        "nitros",
        "perception",
        "pipeline",
        "slam",
        "warp",
    ),
    _("help.panel.platform"): (
        "container",
        "cosmos",
        "groot",
        "native",
        "remote",
        "shell",
    ),
}

HELP_PANEL_OF = {name: panel for panel, names in HELP_PANELS.items() for name in names}

# Pinned above the alphabetical list by the 'core' help order.
CORE_COMMANDS = ("version", "info", "help", "doctor", "init", "setup")


class CaasiGroup(TyperGroup):
    """Root group: orders the help listing per CAASI_HELP_ORDER / `help_order`.

    `grouped` (default) renders one panel per HELP_PANELS entry, `core` pins
    CORE_COMMANDS above an alphabetical list, `alpha` is a single alphabetical
    list. Only the root listing is affected: sub-groups keep the registration
    order their authors chose.
    """

    def list_commands(self, ctx: Context) -> list[str]:
        order = output.help_order()
        names = set(self.commands)
        if order == "alpha":
            return sorted(names)
        if order == "core":
            pinned = [name for name in CORE_COMMANDS if name in names]
            return pinned + sorted(names.difference(CORE_COMMANDS))
        return [name for panel in HELP_PANELS.values() for name in panel]

    def format_help(self, ctx: Context, formatter: HelpFormatter) -> None:
        grouped = output.help_order() == "grouped"
        for name, command in self.commands.items():
            command.rich_help_panel = HELP_PANEL_OF.get(name) if grouped else None
        super().format_help(ctx, formatter)


app = typer.Typer(
    name="caasi",
    help=_("cli.help"),
    no_args_is_help=True,
    add_completion=True,
    rich_markup_mode="rich",
    context_settings={"help_option_names": ["-h", "--help"]},
    cls=CaasiGroup,
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
    color: str = typer.Option("auto", "--color", help=_("cli.flag.color")),
    layout: Optional[str] = typer.Option(None, "--layout", help=_("cli.flag.layout")),
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
    if color not in ("auto", "always", "never"):
        raise typer.BadParameter(
            _("cli.flag.color.invalid", value=color), param_hint="--color"
        )
    if layout is not None and layout not in output.LAYOUTS:
        raise typer.BadParameter(
            _("cli.flag.layout.invalid", value=layout), param_hint="--layout"
        )
    state.configure(
        verbose=verbose,
        quiet=quiet,
        json_output=json_output,
        color=color,
        layout=layout,
        config_path=config,
        lang=lang,
    )


app.command("version", help=_("version.help"))(misc.version_command)
app.command("info", help=_("info.help"))(misc.info_command)
app.command("help", help=_("help.help"))(misc.help_command)
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
app.add_typer(synth_cmd.app, name="synth", help=_("synth.help"))
app.add_typer(teleop_cmd.app, name="teleop", help=_("teleop.help"))
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
app.add_typer(accelerated.isaacros_app, name="isaac-ros", help=_("isaacros.help"))
app.add_typer(accelerated.perception_app, name="perception", help=_("perception.help"))
app.add_typer(accelerated.slam_app, name="slam", help=_("slam.help"))
app.add_typer(accelerated.mapping_app, name="mapping", help=_("mapping.help"))
app.add_typer(accelerated.motion_app, name="motion", help=_("motion.help"))
app.add_typer(accelerated.nitros_app, name="nitros", help=_("nitros.help"))
app.add_typer(accelerated.pipeline_app, name="pipeline", help=_("pipeline.help"))
app.add_typer(platform_cmd.physics_app, name="physics", help=_("physics.help"))
app.add_typer(platform_cmd.warp_app, name="warp", help=_("warp.help"))
app.add_typer(platform_cmd.groot_app, name="groot", help=_("groot.help"))
app.add_typer(platform_cmd.cosmos_app, name="cosmos", help=_("cosmos.help"))
app.add_typer(remote_cmd.app, name="remote", help=_("remote.help"))
app.add_typer(container_cmd.app, name="container", help=_("container.help"))


def run() -> None:
    """Console script entry point (`caasi`)."""
    app()


if __name__ == "__main__":  # pragma: no cover
    run()
