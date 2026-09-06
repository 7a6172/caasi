"""`caasi native` — escape hatch to the native Isaac/ROS tools.

These commands execute the real tools (python.sh, isaaclab.sh, ros2) with
the given arguments and mirror their exit codes. Output is captured and
re-printed so it works in scripts and pipes.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import typer

from .. import state
from ..core import ros as ros_core
from ..i18n import _
from ..utils import output, shell

app = typer.Typer(no_args_is_help=True)

_EXTRA_SETTINGS = {"allow_extra_args": True, "ignore_unknown_options": True}


def _tool_path(tool: str) -> Path | None:
    """Registered install path for isaacsim/isaaclab (config, then env)."""
    cfg = state.cfg()
    resolved = cfg.resolve_tool(tool)
    if resolved and resolved.expanded_path:
        return resolved.expanded_path
    env_var = "ISAACSIM_PATH" if tool == "isaacsim" else "ISAACLAB_PATH"
    env_path = os.environ.get(env_var)
    if env_path:
        candidate = Path(env_path).expanduser()
        if candidate.is_dir():
            return candidate
    return None


def _tool_python(tool: str) -> str | None:
    """Explicit python registered for the tool, if any."""
    resolved = state.cfg().resolve_tool(tool)
    return resolved.python if resolved else None


def _exec(command: list[str]) -> None:
    result = shell.run_cmd(command, timeout=None)
    if result.stdout:
        output.echo(result.stdout.rstrip(), markup=False)
    if result.stderr:
        output.echo(result.stderr.rstrip(), markup=False)
    raise typer.Exit(result.returncode if result.returncode >= 0 else 1)


@app.command("sim", help=_("native.sim_help"), context_settings=_EXTRA_SETTINGS)
def native_sim(ctx: typer.Context) -> None:
    path = _tool_path("isaacsim")
    launcher = path / "python.sh" if path else None
    if not path or launcher is None or not launcher.is_file():
        output.fail(_("native.no_tool", tool="isaacsim"))
        return
    _exec([str(launcher), *[str(a) for a in ctx.args]])


@app.command("lab", help=_("native.lab_help"), context_settings=_EXTRA_SETTINGS)
def native_lab(ctx: typer.Context) -> None:
    path = _tool_path("isaaclab")
    launcher = path / "isaaclab.sh" if path else None
    if not path or launcher is None or not launcher.is_file():
        output.fail(_("native.no_tool", tool="isaaclab"))
        return
    _exec([str(launcher), *[str(a) for a in ctx.args]])


@app.command("ros", help=_("native.ros_help"), context_settings=_EXTRA_SETTINGS)
def native_ros(ctx: typer.Context) -> None:
    binary = ros_core.find_ros2_binary()
    if not binary:
        output.fail(_("native.no_ros2"))
        return
    _exec([binary, *[str(a) for a in ctx.args]])


@app.command("run", help=_("native.run_help"), context_settings=_EXTRA_SETTINGS)
def native_run(
    ctx: typer.Context,
    script: str = typer.Argument(..., help=_("native.arg.script")),
    tool: str = typer.Option("python", "--tool", help=_("native.flag.tool")),
) -> None:
    args = [str(a) for a in ctx.args]
    if tool == "python":
        _exec([sys.executable, script, *args])
        return
    if tool == "sim":
        python = _tool_python("isaacsim")
        if python:
            _exec([python, script, *args])
            return
        path = _tool_path("isaacsim")
        launcher = path / "python.sh" if path else None
        if launcher and launcher.is_file():
            _exec([str(launcher), script, *args])
            return
        output.fail(_("native.no_tool", tool="isaacsim"))
        return
    if tool == "lab":
        python = _tool_python("isaaclab")
        if python:
            _exec([python, script, *args])
            return
        path = _tool_path("isaaclab")
        launcher = path / "isaaclab.sh" if path else None
        if launcher and launcher.is_file():
            _exec([str(launcher), "-p", script, *args])
            return
        output.fail(_("native.no_tool", tool="isaaclab"))
        return
    output.fail(_("native.bad_tool", tool=tool))
