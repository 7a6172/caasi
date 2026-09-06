"""`caasi moveit` — orchestrate MoveIt 2 by delegating to ros2 tooling.

caasi locates and starts MoveIt 2 and checks whether the move_group node is
up; motion planning itself always happens inside MoveIt 2.
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

MOVE_GROUP_PACKAGE = "moveit_ros_move_group"
MOVE_GROUP_NODE = "move_group"


def _binary_or_fail() -> str:
    binary = ros_core.find_ros2_binary()
    if not binary:
        output.fail(_("native.no_ros2"))
        raise typer.Exit(1)  # unreachable
    return binary


def _moveit_prefix() -> Path | None:
    return ros_core.pkg_prefix(MOVE_GROUP_PACKAGE)


def _move_group_running() -> list[str]:
    nodes = ros_core.ros2_lines(["node", "list"])
    return [node for node in nodes if MOVE_GROUP_NODE in node]


@app.command("status", help=_("moveit.status_help"))
def moveit_status(
    json_output: bool = typer.Option(False, "--json", help=_("flag.json")),
) -> None:
    _binary_or_fail()
    prefix = _moveit_prefix()
    nodes = _move_group_running()
    payload = {
        "installed": prefix is not None,
        "package": str(prefix) if prefix else None,
        "move_group_nodes": nodes,
    }
    if output.wants_json(json_output):
        output.echo_json(payload)
        return
    output.echo(f"[bold]{_('moveit.title')}[/bold]")
    output.echo(
        f"  {_('moveit.row.package'):<12} {prefix if prefix else _('moveit.not_installed')}"
    )
    running = ", ".join(nodes) if nodes else _("moveit.no_move_group")
    output.echo(f"  {_('moveit.row.move_group'):<12} {running}")


@app.command("launch", help=_("moveit.launch_help"), context_settings=_EXTRA_SETTINGS)
def moveit_launch(
    ctx: typer.Context,
    target: str = typer.Argument(..., help=_("moveit.arg.target")),
    package: Optional[str] = typer.Option(None, "--package", "-p", help=_("moveit.flag.package")),
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
        state.cfg(), name=run_name, command=command, backend="ros", kind="moveit",
        extra={"launch": target, "package": package},
    )
    if output.wants_json(json_output):
        output.echo_json(record.to_dict())
        return
    output.echo(f"[green]{_('ros.started', id=record.run_id)}[/green]")
    output.echo(f"  [dim]{_('sim.run.watch', id=record.run_id)}[/dim]")


@app.command("plan", help=_("moveit.plan_help"))
def moveit_plan(
    group: Optional[str] = typer.Option(None, "--group", "-g", help=_("moveit.flag.group")),
    json_output: bool = typer.Option(False, "--json", help=_("flag.json")),
) -> None:
    _binary_or_fail()
    nodes = _move_group_running()
    ready = bool(nodes)
    if output.wants_json(json_output):
        output.echo_json(
            {"ready": ready, "group": group, "move_group_nodes": nodes}
        )
        raise typer.Exit(0 if ready else 1)
    if not ready:
        output.fail(_("moveit.no_move_group"))
        return
    where = f" ({_('moveit.arg.group')}: {group})" if group else ""
    output.echo(f"[green]{_('moveit.plan_ready', nodes=', '.join(nodes))}[/green]{where}")


@app.command("test", help=_("moveit.test_help"))
def moveit_test(
    json_output: bool = typer.Option(False, "--json", help=_("flag.json")),
) -> None:
    binary = ros_core.find_ros2_binary()
    prefix = _moveit_prefix() if binary else None
    nodes = _move_group_running() if binary else []
    checks = [
        {"check": "ros2", "ok": bool(binary), "detail": binary or _("native.no_ros2")},
        {
            "check": MOVE_GROUP_PACKAGE,
            "ok": prefix is not None,
            "detail": str(prefix) if prefix else _("moveit.not_installed"),
        },
        {
            "check": MOVE_GROUP_NODE,
            "ok": bool(nodes),
            "detail": ", ".join(nodes) if nodes else _("moveit.no_move_group"),
        },
    ]
    ok = all(check["ok"] for check in checks)
    if output.wants_json(json_output):
        output.echo_json({"ok": ok, "checks": checks})
        raise typer.Exit(0 if ok else 1)
    for check in checks:
        symbol, style = output.status_symbol("ok" if check["ok"] else "fail")
        output.echo(f"[{style}]{symbol}[/] {check['check']:<22} {check['detail']}")
    if not ok:
        output.fail(_("moveit.fail"))
        return
    output.echo(f"[green]{_('moveit.pass')}[/green]")
