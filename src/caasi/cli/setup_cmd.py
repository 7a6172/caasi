"""`caasi setup` — detect missing ecosystem components and guide installation."""

from __future__ import annotations

from typing import Optional

import typer

from .. import state
from ..checks.isaac import detect_isaac_lab, detect_isaac_sim
from ..core import ros as ros_core
from ..i18n import _
from ..utils import output, pydist, shell

COMPONENTS: tuple[str, ...] = ("isaacsim", "isaaclab", "ros2", "pytorch", "docker")
# Components whose absence makes `caasi setup` (summary mode) exit non-zero.
CORE_COMPONENTS: frozenset[str] = frozenset({"isaacsim", "isaaclab", "ros2"})

Detection = tuple[str, str]  # (status, detail)


def detect_component(component: str) -> Detection:
    cfg = state.cfg()
    if component == "isaacsim":
        status, detail, _hint = detect_isaac_sim(cfg)
        return status, detail
    if component == "isaaclab":
        status, detail, _hint = detect_isaac_lab(cfg)
        return status, detail
    if component == "ros2":
        distro, _root = ros_core.find_distro()
        binary = ros_core.find_ros2_binary()
        if distro and binary:
            return "ok", f"distro '{distro}', ros2 at {binary}"
        if distro:
            return "warn", f"distro '{distro}' found but the ros2 CLI is missing"
        return "fail", _("setup.ros2.missing")
    if component == "pytorch":
        version = pydist.pip_version("torch")
        return ("ok", f"torch {version}") if version else ("fail", _("setup.not_installed"))
    # docker
    if shell.which("docker"):
        result = shell.run_cmd(["docker", "--version"], timeout=5)
        if result.ok:
            return "ok", result.stdout.strip().splitlines()[0]
        return "warn", _("setup.probe_failed")
    return "skip", _("setup.not_installed")


def setup_command(
    component: Optional[str] = typer.Argument(None, help=_("setup.arg.component")),
    json_output: bool = typer.Option(False, "--json", help=_("flag.json")),
) -> None:
    if component and component not in COMPONENTS:
        output.fail(
            _("setup.unknown_component", component=component, valid=", ".join(COMPONENTS))
        )
        return

    statuses = {name: detect_component(name) for name in COMPONENTS}
    missing = [name for name in COMPONENTS if name in CORE_COMPONENTS and statuses[name][0] == "fail"]

    if component:
        status, detail = statuses[component]
        if output.wants_json(json_output):
            output.echo_json(
                {"component": component, "status": status, "detail": detail,
                 "guide": _(f"setup.guide.{component}")}
            )
            raise typer.Exit(1 if status == "fail" else 0)
        symbol, style = output.status_symbol(status)
        output.echo(f"[{style}]{symbol}[/] [bold]{component}[/bold] — {detail}")
        output.echo()
        output.echo(_(f"setup.guide.{component}"))
        raise typer.Exit(1 if status == "fail" else 0)

    if output.wants_json(json_output):
        output.echo_json(
            {
                "components": {
                    name: {"status": status, "detail": detail}
                    for name, (status, detail) in statuses.items()
                },
                "missing": missing,
            }
        )
        raise typer.Exit(1 if missing else 0)

    from rich.table import Table

    table = Table(header_style="bold", **output.table_styles())
    table.add_column(_("setup.col.component"))
    table.add_column(_("setup.col.status"))
    table.add_column(_("setup.col.detail"))
    for name, (status, detail) in statuses.items():
        symbol, style = output.status_symbol(status)
        table.add_row(name, f"[{style}]{symbol} {status}[/]", detail)
    output.echo(table)
    if missing:
        output.echo(
            f"[yellow]{_('setup.missing', components=', '.join(missing))}[/yellow]"
        )
    raise typer.Exit(1 if missing else 0)
