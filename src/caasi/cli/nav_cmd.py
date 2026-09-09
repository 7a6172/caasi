"""`caasi nav` — orchestrate Nav2 by delegating to ros2 launch/pkg.

caasi only locates and starts the Nav2 stack; the navigation itself stays
inside Nav2 ("use Nav2, don't become another Nav2").
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import typer
import yaml

from .. import state
from ..checks import CheckResult, run_checks
from ..core import ros as ros_core
from ..core import runs
from ..i18n import _
from ..utils import output
from . import ecosystem as eco

app = typer.Typer(no_args_is_help=True)

DOCTOR_SECTIONS = ["ros", "robotics"]

_EXTRA_SETTINGS = {"allow_extra_args": True, "ignore_unknown_options": True}

BRINGUP_PACKAGE = "nav2_bringup"
BRINGUP_LAUNCH = "bringup_launch.py"

# Node names that indicate a running Nav2 stack.
NAV_NODES = (
    "bt_navigator",
    "planner_server",
    "controller_server",
    "behavior_server",
    "recoveries_server",
    "smoother_server",
    "waypoint_follower",
    "amcl",
    "velocity_smoother",
)


def _binary_or_fail() -> str:
    binary = ros_core.find_ros2_binary()
    if not binary:
        output.fail(_("native.no_ros2"))
        raise typer.Exit(1)  # unreachable
    return binary


def _bringup_prefix() -> Path | None:
    return ros_core.pkg_prefix(BRINGUP_PACKAGE)


def _running_nav_nodes() -> list[str]:
    nodes = ros_core.ros2_lines(["node", "list"])
    return [node for node in nodes if any(key in node for key in NAV_NODES)]


def _default_params_file(prefix: Path | None) -> Path | None:
    if prefix is None:
        return None
    return prefix / "share" / BRINGUP_PACKAGE / "params" / "nav2_params.yaml"


@app.command("status", help=_("nav.status_help"))
def nav_status(
    json_output: bool = typer.Option(False, "--json", help=_("flag.json")),
) -> None:
    _binary_or_fail()
    prefix = _bringup_prefix()
    nodes = _running_nav_nodes()
    payload = {
        "installed": prefix is not None,
        "bringup": str(prefix) if prefix else None,
        "nodes": nodes,
    }
    if output.wants_json(json_output):
        output.echo_json(payload)
        return
    output.echo(f"[bold]{_('nav.title')}[/bold]")
    output.echo(f"  {_('nav.row.bringup'):<10} {prefix if prefix else _('nav.not_installed')}")
    running = ", ".join(nodes) if nodes else _("nav.no_nodes")
    output.echo(f"  {_('nav.row.nodes'):<10} {running}")


@app.command("launch", help=_("nav.launch_help"), context_settings=_EXTRA_SETTINGS)
def nav_launch(
    ctx: typer.Context,
    params: Optional[Path] = typer.Option(None, "--params", help=_("nav.flag.params")),
    map_file: Optional[Path] = typer.Option(None, "--map", help=_("nav.flag.map")),
    dry_run: bool = typer.Option(False, "--dry-run", help=_("nav.flag.dry_run")),
    json_output: bool = typer.Option(False, "--json", help=_("flag.json")),
) -> None:
    binary = _binary_or_fail()
    if _bringup_prefix() is None:
        output.fail(_("nav.not_installed"))
        return
    command = [binary, "launch", BRINGUP_PACKAGE, BRINGUP_LAUNCH]
    if map_file is not None:
        command.append(f"map:={map_file}")
    if params is not None:
        command.append(f"params_file:={params}")
    command += [str(a) for a in ctx.args]

    if dry_run:
        output.echo(f"[bold]{_('replay.dry_title')}[/bold]")
        output.echo(f"  command: {' '.join(command)}")
        return

    record = runs.start_run(
        state.cfg(), name="nav2-bringup", command=command, backend="ros", kind="nav",
        extra={"params": str(params) if params else None, "map": str(map_file) if map_file else None},
    )
    if output.wants_json(json_output):
        output.echo_json(record.to_dict())
        return
    output.echo(f"[green]{_('ros.started', id=record.run_id)}[/green]")
    output.echo(f"  [dim]{_('sim.run.watch', id=record.run_id)}[/dim]")


@app.command("inspect", help=_("nav.inspect_help"))
def nav_inspect(
    params_file: Optional[Path] = typer.Argument(None, help=_("nav.arg.params")),
    json_output: bool = typer.Option(False, "--json", help=_("flag.json")),
) -> None:
    _binary_or_fail()
    path = params_file or _default_params_file(_bringup_prefix())
    if path is None or not path.is_file():
        output.fail(_("nav.params_missing", path=str(path) if path else "-"))
        return
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        output.fail(str(exc))
        return
    nodes = sorted(data.keys()) if isinstance(data, dict) else []
    if output.wants_json(json_output):
        output.echo_json({"path": str(path), "nodes": nodes})
        return
    output.echo(f"[bold]{_('nav.title')}[/bold]")
    output.echo(f"  {_('nav.row.params'):<10} {path}")
    output.echo(f"  {_('nav.row.nodes'):<10} {len(nodes)}")
    for node in nodes:
        output.echo(f"    {node}", markup=False)


@app.command("test", help=_("nav.test_help"))
def nav_test(
    json_output: bool = typer.Option(False, "--json", help=_("flag.json")),
) -> None:
    binary = ros_core.find_ros2_binary()
    prefix = _bringup_prefix() if binary else None
    nodes = _running_nav_nodes() if binary else []
    checks = [
        {"check": "ros2", "ok": bool(binary), "detail": binary or _("native.no_ros2")},
        {
            "check": BRINGUP_PACKAGE,
            "ok": prefix is not None,
            "detail": str(prefix) if prefix else _("nav.not_installed"),
        },
        {
            "check": "nodes",
            "ok": bool(nodes),
            "detail": ", ".join(nodes) if nodes else _("nav.no_nodes"),
        },
    ]
    ok = all(check["ok"] for check in checks)
    if output.wants_json(json_output):
        output.echo_json({"ok": ok, "checks": checks})
        raise typer.Exit(0 if ok else 1)
    for check in checks:
        symbol, style = output.status_symbol("ok" if check["ok"] else "fail")
        output.echo(f"[{style}]{symbol}[/] {check['check']:<16} {check['detail']}")
    if not ok:
        output.fail(_("nav.fail"))
        return
    output.echo(f"[green]{_('nav.pass')}[/green]")


def _skip(name: str) -> CheckResult:
    return CheckResult(
        "robotics", name, "skip", _("doctor.robotics.no_ros2"), _("doctor.robotics.no_ros2_hint")
    )


def _doctor_extras() -> list[CheckResult]:
    """Nav2-specific rows: the params file and the lifecycle nodes."""
    if not ros_core.find_ros2_binary():
        return [_skip(_("nav.doctor.params")), _skip(_("nav.doctor.nodes"))]

    results: list[CheckResult] = []
    prefix = _bringup_prefix()
    params = _default_params_file(prefix)
    if params is not None and params.is_file():
        results.append(CheckResult("robotics", _("nav.doctor.params"), "ok", str(params)))
    else:
        detail = _("nav.not_installed") if prefix is None else _("nav.params_missing", path=str(params))
        results.append(
            CheckResult(
                "robotics",
                _("nav.doctor.params"),
                "fail",
                detail,
                _("nav.doctor.params_hint"),
            )
        )
    nodes = _running_nav_nodes()
    if nodes:
        results.append(
            CheckResult("robotics", _("nav.doctor.nodes"), "ok", ", ".join(nodes))
        )
    else:
        results.append(
            CheckResult(
                "robotics",
                _("nav.doctor.nodes"),
                "warn",
                _("nav.no_nodes"),
                _("nav.doctor.nodes_hint"),
            )
        )
    return results


@app.command("doctor", help=_("nav.doctor_help"))
def nav_doctor(
    verbose: bool = typer.Option(False, "--verbose", help=_("doctor.flag.verbose")),
    json_output: bool = typer.Option(False, "--json", help=_("flag.json")),
) -> None:
    results = run_checks(DOCTOR_SECTIONS, state.cfg())
    results.extend(_doctor_extras())
    eco.render_checks(
        {"group": "nav", "sections": DOCTOR_SECTIONS}, results, verbose, json_output
    )
