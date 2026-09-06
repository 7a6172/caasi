"""`caasi control` — manage ros2_control controllers via the ros2 CLI."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import typer
import yaml

from ..core import ros as ros_core
from ..i18n import _
from ..utils import output

app = typer.Typer(no_args_is_help=True)

CONTROL_PACKAGE = "ros2controlcli"


def _binary_or_fail() -> str:
    binary = ros_core.find_ros2_binary()
    if not binary:
        output.fail(_("native.no_ros2"))
        raise typer.Exit(1)  # unreachable
    return binary


def _control_prefix() -> Path | None:
    return ros_core.pkg_prefix(CONTROL_PACKAGE)


def _manager_nodes() -> list[str]:
    nodes = ros_core.ros2_lines(["node", "list"])
    return [node for node in nodes if "controller_manager" in node]


@app.command("status", help=_("control.status_help"))
def control_status(
    json_output: bool = typer.Option(False, "--json", help=_("flag.json")),
) -> None:
    _binary_or_fail()
    prefix = _control_prefix()
    nodes = _manager_nodes()
    payload = {
        "installed": prefix is not None,
        "package": str(prefix) if prefix else None,
        "managers": nodes,
    }
    if output.wants_json(json_output):
        output.echo_json(payload)
        return
    output.echo(f"[bold]{_('control.title')}[/bold]")
    output.echo(
        f"  {_('control.row.package'):<16} {prefix if prefix else _('control.not_installed')}"
    )
    managers = ", ".join(nodes) if nodes else _("control.no_managers")
    output.echo(f"  {_('control.row.managers'):<16} {managers}")


@app.command("list", help=_("control.list_help"))
def control_list(
    json_output: bool = typer.Option(False, "--json", help=_("flag.json")),
) -> None:
    _binary_or_fail()
    result = ros_core.run_ros2(["control", "list_controllers"])
    if not result.ok:
        output.fail(_("control.not_installed"))
        return
    lines = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    if output.wants_json(json_output):
        output.echo_json(lines)
        return
    if not lines:
        output.echo(f"[yellow]{_('control.no_controllers')}[/yellow]")
        return
    for line in lines:
        output.echo(line, markup=False)


@app.command("check", help=_("control.check_help"))
def control_check(
    params_file: Optional[Path] = typer.Argument(None, help=_("control.arg.params")),
    json_output: bool = typer.Option(False, "--json", help=_("flag.json")),
) -> None:
    if params_file is None:
        output.fail(_("control.params_required"))
        return
    if not params_file.is_file():
        output.fail(_("nav.params_missing", path=str(params_file)))
        return
    try:
        data = yaml.safe_load(params_file.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        output.fail(str(exc))
        return

    issues: list[str] = []
    controllers: list[str] = []
    if not isinstance(data, dict):
        issues.append(_("control.issue.mapping"))
    else:
        manager = data.get("controller_manager")
        if not isinstance(manager, dict):
            issues.append(_("control.issue.no_manager"))
        else:
            params = manager.get("ros__parameters") or {}
            if not isinstance(params, dict):
                issues.append(_("control.issue.no_manager"))
            else:
                if "update_rate" not in params:
                    issues.append(_("control.issue.no_rate"))
                for key, value in params.items():
                    if not isinstance(value, dict):
                        continue
                    controllers.append(key)
                    if "type" not in value:
                        issues.append(_("control.issue.no_type", controller=key))
    ok = not issues
    if output.wants_json(json_output):
        output.echo_json(
            {"path": str(params_file), "controllers": controllers, "issues": issues, "ok": ok}
        )
        raise typer.Exit(0 if ok else 1)
    for controller in controllers:
        symbol, style = output.status_symbol("ok")
        output.echo(f"[{style}]{symbol}[/] {controller}")
    for issue in issues:
        symbol, style = output.status_symbol("fail")
        output.echo(f"[{style}]{symbol}[/] {issue}")
    if not ok:
        raise typer.Exit(1)
    output.echo(f"[green]{_('control.check_ok', count=len(controllers))}[/green]")
