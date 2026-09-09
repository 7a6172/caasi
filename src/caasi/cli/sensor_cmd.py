"""`caasi sensor` — discover and test sensors and sensor SDKs."""

from __future__ import annotations

import typer
from rich.table import Table

from .. import state
from ..core import sensors as sensors_core
from ..core.sensors import SensorInfo
from ..i18n import _
from ..utils import output

app = typer.Typer(no_args_is_help=True)


def _require_sensor(name: str) -> SensorInfo:
    entries = sensors_core.detect_sensors(state.cfg())
    for entry in entries:
        if entry.name == name:
            return entry
    output.fail(
        _("sensor.not_found", name=name, valid=", ".join(e.name for e in entries))
    )
    raise typer.Exit(1)  # unreachable, keeps type-checkers happy


@app.command("list", help=_("sensor.list_help"))
def sensor_list(
    json_output: bool = typer.Option(False, "--json", help=_("flag.json")),
) -> None:
    entries = sensors_core.detect_sensors(state.cfg())
    if output.wants_json(json_output):
        output.echo_json(
            [
                {
                    "name": e.name,
                    "kind": e.kind,
                    "detected": e.detected,
                    "detail": e.detail,
                    "devices": e.devices,
                    "hint": e.hint,
                }
                for e in entries
            ]
        )
        return
    table = Table(header_style="bold", **output.table_styles())
    table.add_column(_("sensor.col.name"))
    table.add_column(_("sensor.col.kind"))
    table.add_column(_("sensor.col.status"))
    table.add_column(_("sensor.col.detail"))
    for entry in entries:
        if entry.detected:
            status = f"[green]{_('sensor.detected')}[/green]"
        else:
            status = f"[dim]{_('sensor.not_detected')}[/dim]"
        table.add_row(entry.name, entry.kind, status, entry.detail)
    output.echo(table)


@app.command("inspect", help=_("sensor.inspect_help"))
def sensor_inspect(
    name: str = typer.Argument(..., help=_("sensor.arg.name")),
    json_output: bool = typer.Option(False, "--json", help=_("flag.json")),
) -> None:
    entry = _require_sensor(name)
    payload = {
        "name": entry.name,
        "kind": entry.kind,
        "detected": entry.detected,
        "detail": entry.detail,
        "devices": entry.devices,
        "hint": entry.hint,
    }
    if output.wants_json(json_output):
        output.echo_json(payload)
        return
    status = _("sensor.detected") if entry.detected else _("sensor.not_detected")
    output.echo(f"[bold]{entry.name}[/bold] [dim]({entry.kind})[/dim] — {status}")
    output.echo(f"  {entry.detail}")
    output.echo(f"  [bold]{_('sensor.devices')}[/bold]: "
                + (", ".join(entry.devices) if entry.devices else _("sensor.no_devices")))
    if entry.hint:
        output.echo(f"  [dim]{_('sensor.hint')}: {entry.hint}[/dim]")


@app.command("test", help=_("sensor.test_help"))
def sensor_test(
    name: str = typer.Argument(..., help=_("sensor.arg.name")),
    json_output: bool = typer.Option(False, "--json", help=_("flag.json")),
) -> None:
    entry = _require_sensor(name)
    if output.wants_json(json_output):
        output.echo_json(
            {"name": entry.name, "ok": entry.detected, "detail": entry.detail}
        )
        raise typer.Exit(0 if entry.detected else 1)
    if entry.detected:
        output.echo(f"[green]{_('sensor.pass', name=entry.name, detail=entry.detail)}[/green]")
        return
    output.echo(f"[red]{_('sensor.fail', name=entry.name, detail=entry.detail)}[/red]")
    if entry.hint:
        output.echo(f"  [dim]{entry.hint}[/dim]")
    raise typer.Exit(1)
