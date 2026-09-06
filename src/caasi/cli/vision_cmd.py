"""`caasi vision` — diagnose the computer-vision stack."""

from __future__ import annotations

import sys
from typing import Optional

import typer
from rich.table import Table

from ..core import vision as vision_core
from ..i18n import _
from ..utils import output

app = typer.Typer(no_args_is_help=True)


@app.command("status", help=_("vision.status_help"))
def vision_status(
    json_output: bool = typer.Option(False, "--json", help=_("flag.json")),
) -> None:
    components = vision_core.component_status()
    if output.wants_json(json_output):
        output.echo_json(
            [
                {
                    "name": c.name,
                    "installed": c.installed,
                    "version": c.version,
                    "module": c.module,
                }
                for c in components
            ]
        )
        return
    table = Table(title=_("vision.title"), header_style="bold")
    table.add_column(_("vision.col.component"))
    table.add_column(_("vision.col.status"))
    table.add_column(_("vision.col.version"))
    table.add_column(_("vision.col.module"))
    for component in components:
        status = (
            f"[green]{_('vision.installed')}[/green]"
            if component.installed
            else f"[red]{_('vision.missing')}[/red]"
        )
        table.add_row(
            component.name, status, component.version or "—", component.module or "—"
        )
    output.echo(table)
    output.echo(f"[dim]{_('vision.hint')}[/dim]")


@app.command("inspect", help=_("vision.inspect_help"))
def vision_inspect(
    component_name: str = typer.Argument(..., help=_("vision.arg.component")),
    json_output: bool = typer.Option(False, "--json", help=_("flag.json")),
) -> None:
    component = vision_core.find_component(component_name)
    if component is None:
        output.fail(
            _("vision.not_found", name=component_name,
              valid=", ".join(vision_core.COMPONENTS))
        )
        return
    payload = {
        "name": component.name,
        "installed": component.installed,
        "version": component.version,
        "module": component.module,
    }
    if output.wants_json(json_output):
        output.echo_json(payload)
        return
    status = _("vision.installed") if component.installed else _("vision.missing")
    output.echo(
        f"[bold]{component.name}[/bold] — {status}"
        + (f" [dim](version {component.version})[/dim]" if component.version else "")
    )
    output.echo(f"  [bold]{_('vision.col.module')}[/bold]: {component.module}")
    if not component.installed:
        output.echo(f"  [dim]{_('vision.hint')}[/dim]")


@app.command("test", help=_("vision.test_help"))
def vision_test(
    components: Optional[list[str]] = typer.Argument(None, help=_("vision.arg.component")),
    python: Optional[str] = typer.Option(None, "--python", help=_("vision.flag.python")),
    json_output: bool = typer.Option(False, "--json", help=_("flag.json")),
) -> None:
    names = components or list(vision_core.COMPONENTS)
    unknown = [n for n in names if n not in vision_core.COMPONENTS]
    if unknown:
        output.fail(
            _("vision.not_found", name=unknown[0],
              valid=", ".join(vision_core.COMPONENTS))
        )
        return

    interpreter = python or sys.executable
    results = []
    for name in names:
        component = vision_core.find_component(name)
        assert component is not None
        if not component.installed or not component.module:
            results.append({"name": name, "ok": False, "detail": _("vision.missing")})
            continue
        probe = vision_core.probe(interpreter, component.module)
        detail = (probe.stdout.strip() or probe.stderr.strip()).splitlines()
        results.append(
            {"name": name, "ok": probe.ok, "detail": detail[-1] if detail else ""}
        )

    if output.wants_json(json_output):
        output.echo_json(results)
        raise typer.Exit(0 if all(r["ok"] for r in results) else 1)
    for result in results:
        style = "green" if result["ok"] else "red"
        output.echo(f"[{style}]{result['name']}[/]: {result['detail']}")
    if not all(r["ok"] for r in results):
        raise typer.Exit(1)
