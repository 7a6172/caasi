"""`caasi ros` — orchestrate ROS 2 by delegating to the real ros2 CLI.

The CLI never imports rclpy; every operation is a subprocess call into the
discovered distro's ros2 binary. Long-lived commands (launch, topic echo)
become tracked runs.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

import typer

from .. import state
from ..core import ros as ros_core
from ..core import runs
from ..i18n import _
from ..utils import output

app = typer.Typer(no_args_is_help=True)

_EXTRA_SETTINGS = {"allow_extra_args": True, "ignore_unknown_options": True}

LIST_KINDS = {"topics": "topic", "nodes": "node", "services": "service", "actions": "action"}


def _binary_or_fail() -> str:
    binary = ros_core.find_ros2_binary()
    if not binary:
        output.fail(_("native.no_ros2"))
        raise typer.Exit(1)  # unreachable, keeps type-checkers happy
    return binary


def _print_result(result) -> int:
    """Echo a ShellResult's output and return its exit code."""
    if result.stdout:
        output.echo(result.stdout.rstrip(), markup=False)
    if result.stderr:
        output.echo(result.stderr.rstrip(), markup=False)
    return result.returncode if result.returncode >= 0 else 1


@app.command("status", help=_("ros.status_help"))
def ros_status(
    json_output: bool = typer.Option(False, "--json", help=_("flag.json")),
) -> None:
    distro, root = ros_core.find_distro()
    binary = ros_core.find_ros2_binary()
    rmw = os.environ.get("RMW_IMPLEMENTATION")
    topics = ros_core.ros2_lines(["topic", "list"]) if binary else []
    payload = {
        "available": bool(binary),
        "distro": distro,
        "root": str(root) if root else None,
        "binary": binary,
        "rmw": rmw,
        "topics": len(topics),
    }
    if output.wants_json(json_output):
        output.echo_json(payload)
        return
    output.echo(f"[bold]{_('ros.title')}[/bold]")
    for label, value in (
        (_("ros.row.distro"), distro or _("ros.missing")),
        (_("ros.row.root"), str(root) if root else _("ros.missing")),
        (_("ros.row.binary"), binary or _("ros.missing")),
        (_("ros.row.rmw"), rmw or "(default)"),
        (_("ros.row.topics"), str(len(topics)) if binary else _("ros.missing")),
    ):
        output.echo(f"  {label:<10} {value}")
    if not binary:
        output.echo(f"  [yellow]{_('native.no_ros2')}[/yellow]")


@app.command("doctor", help=_("ros.doctor_help"))
def ros_doctor(
    json_output: bool = typer.Option(False, "--json", help=_("flag.json")),
) -> None:
    try:
        result = ros_core.run_ros2(["doctor"], timeout=60.0)
    except ros_core.RosError as exc:
        output.fail(str(exc))
        return
    text = "\n".join(part for part in (result.stdout, result.stderr) if part)
    if output.wants_json(json_output):
        output.echo_json({"returncode": result.returncode, "output": text})
        raise typer.Exit(result.returncode if result.returncode >= 0 else 1)
    code = _print_result(result)
    raise typer.Exit(code)


@app.command("list", help=_("ros.list_help"))
def ros_list(
    kind: str = typer.Argument(..., help=_("ros.arg.kind")),
    json_output: bool = typer.Option(False, "--json", help=_("flag.json")),
) -> None:
    sub = LIST_KINDS.get(kind)
    if sub is None:
        output.fail(_("ros.bad_kind", kind=kind, valid=", ".join(LIST_KINDS)))
        return
    _binary_or_fail()
    lines = ros_core.ros2_lines([sub, "list"])
    if output.wants_json(json_output):
        output.echo_json(lines)
        return
    if not lines:
        output.echo(f"[yellow]{_('ros.empty', kind=kind)}[/yellow]")
        return
    output.echo(f"[bold]{_('ros.list_title', kind=kind)}[/bold]")
    for line in lines:
        output.echo(f"  {line}", markup=False)


@app.command("launch", help=_("ros.launch_help"), context_settings=_EXTRA_SETTINGS)
def ros_launch(
    ctx: typer.Context,
    target: str = typer.Argument(..., help=_("ros.arg.launch_file")),
    package: Optional[str] = typer.Option(None, "--package", "-p", help=_("ros.flag.package")),
    name: Optional[str] = typer.Option(None, "--name", help=_("ros.flag.name")),
    dry_run: bool = typer.Option(False, "--dry-run", help=_("ros.flag.dry_run")),
    json_output: bool = typer.Option(False, "--json", help=_("flag.json")),
) -> None:
    binary = _binary_or_fail()
    if package is None and os.sep in target and not Path(target).is_file():
        output.fail(_("ros.launch_missing", path=target))
        return
    command = [binary, "launch", *([package] if package else []), target, *[str(a) for a in ctx.args]]
    run_name = name or Path(target).stem

    if dry_run:
        output.echo(f"[bold]{_('replay.dry_title')}[/bold]")
        output.echo(f"  command: {' '.join(command)}")
        return

    record = runs.start_run(
        state.cfg(), name=run_name, command=command, backend="ros", kind="ros",
        extra={"launch": target, "package": package},
    )
    if output.wants_json(json_output):
        output.echo_json(record.to_dict())
        return
    output.echo(f"[green]{_('ros.started', id=record.run_id)}[/green]")
    output.echo(f"  [dim]{_('sim.run.watch', id=record.run_id)}[/dim]")


@app.command("topic", help=_("ros.topic_help"), context_settings=_EXTRA_SETTINGS)
def ros_topic(
    ctx: typer.Context,
    name: str = typer.Argument(..., help=_("ros.arg.topic")),
    echo_stream: bool = typer.Option(False, "--echo", help=_("ros.flag.echo")),
    dry_run: bool = typer.Option(False, "--dry-run", help=_("ros.flag.dry_run")),
    json_output: bool = typer.Option(False, "--json", help=_("flag.json")),
) -> None:
    binary = _binary_or_fail()
    if echo_stream:
        command = [binary, "topic", "echo", name, *[str(a) for a in ctx.args]]
        if dry_run:
            output.echo(f"[bold]{_('replay.dry_title')}[/bold]")
            output.echo(f"  command: {' '.join(command)}")
            return
        record = runs.start_run(
            state.cfg(), name=f"echo-{name.strip('/').replace('/', '-')}",
            command=command, backend="ros", kind="ros",
            extra={"topic": name, "echo": True},
        )
        if output.wants_json(json_output):
            output.echo_json(record.to_dict())
            return
        output.echo(f"[green]{_('ros.started', id=record.run_id)}[/green]")
        output.echo(f"  [dim]{_('sim.run.watch', id=record.run_id)}[/dim]")
        return
    result = ros_core.run_ros2(["topic", "info", name])
    if not result.ok:
        output.fail(_("ros.no_topic", name=name))
        return
    if output.wants_json(json_output):
        output.echo_json({"topic": name, "info": result.stdout.strip()})
        return
    output.echo(result.stdout.rstrip(), markup=False)


@app.command("node", help=_("ros.node_help"))
def ros_node(
    name: str = typer.Argument(..., help=_("ros.arg.node")),
    json_output: bool = typer.Option(False, "--json", help=_("flag.json")),
) -> None:
    _binary_or_fail()
    result = ros_core.run_ros2(["node", "info", name])
    if not result.ok:
        output.fail(_("ros.no_node", name=name))
        return
    if output.wants_json(json_output):
        output.echo_json({"node": name, "info": result.stdout.strip()})
        return
    output.echo(result.stdout.rstrip(), markup=False)


@app.command("graph", help=_("ros.graph_help"))
def ros_graph(
    json_output: bool = typer.Option(False, "--json", help=_("flag.json")),
) -> None:
    _binary_or_fail()
    nodes = ros_core.ros2_lines(["node", "list"])
    topics = ros_core.ros2_lines(["topic", "list"])
    if output.wants_json(json_output):
        output.echo_json({"nodes": nodes, "topics": topics})
        return
    output.echo(f"[bold]{_('ros.graph_title')}[/bold]")
    output.echo(f"  [dim]{_('ros.col.node')} ({len(nodes)})[/dim]")
    for line in nodes:
        output.echo(f"    {line}", markup=False)
    output.echo(f"  [dim]{_('ros.col.topic')} ({len(topics)})[/dim]")
    for line in topics:
        output.echo(f"    {line}", markup=False)
