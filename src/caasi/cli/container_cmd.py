"""`caasi container` — run experiments inside official container images.

caasi detects Docker/Podman, lists Isaac images and builds `docker run`
commands; the runtime does the actual work.
"""

from __future__ import annotations

from pathlib import Path

import typer

from .. import state
from ..core import containers as containers_core
from ..core import runs
from ..i18n import _
from ..utils import output

app = typer.Typer(no_args_is_help=True)

_EXTRA_SETTINGS = {"allow_extra_args": True, "ignore_unknown_options": True}


@app.command("list", help=_("container.list_help"))
def container_list(
    json_output: bool = typer.Option(False, "--json", help=_("flag.json")),
) -> None:
    tool = containers_core.find_container_tool()
    known = [entry["image"] for entry in containers_core.KNOWN_IMAGES]
    local = containers_core.local_images(tool) if tool else []
    if output.wants_json(json_output):
        output.echo_json({"tool": tool, "known": known, "local": local})
        return
    output.echo(
        f"[bold]{_('container.title')}[/bold]  [dim]({_('container.row.tool')}: "
        f"{Path(tool).name if tool else _('container.missing')})[/dim]"
    )
    output.echo(f"  [dim]{_('container.known_title')}[/dim]")
    for entry in containers_core.KNOWN_IMAGES:
        output.echo(f"    {entry['image']:<32} {entry['description']}")
    output.echo(f"  [dim]{_('container.local_title')}[/dim]")
    if not local:
        output.echo(f"    [dim]{_('container.no_local')}[/dim]")
    for image in local:
        output.echo(f"    {image}")
    if not tool:
        output.echo(f"  [yellow]{_('container.no_tool')}[/yellow]")


@app.command("check", help=_("container.check_help"))
def container_check(
    json_output: bool = typer.Option(False, "--json", help=_("flag.json")),
) -> None:
    tool = containers_core.find_container_tool()
    daemon = containers_core.daemon_ok(tool) if tool else False
    gpu = containers_core.nvidia_runtime(tool) if tool and daemon else False
    checks = [
        {"check": "tool", "ok": bool(tool), "detail": tool or _("container.no_tool")},
        {"check": "daemon", "ok": daemon, "detail": _("container.daemon_ok") if daemon else _("container.daemon_fail")},
        {"check": "nvidia-runtime", "ok": gpu, "detail": _("container.gpu_ok") if gpu else _("container.gpu_fail")},
    ]
    ok = all(check["ok"] for check in checks)
    if output.wants_json(json_output):
        output.echo_json({"ok": ok, "checks": checks})
        raise typer.Exit(0 if ok else 1)
    for check in checks:
        symbol, style = output.status_symbol("ok" if check["ok"] else "fail")
        output.echo(f"[{style}]{symbol}[/] {check['check']:<16} {check['detail']}")
    if not ok:
        output.fail(_("container.fail"))
        return
    output.echo(f"[green]{_('container.pass')}[/green]")


@app.command("run", help=_("container.run_help"), context_settings=_EXTRA_SETTINGS)
def container_run(
    ctx: typer.Context,
    image: str = typer.Argument(..., help=_("container.arg.image")),
    gpus: str = typer.Option("all", "--gpus", help=_("container.flag.gpus")),
    dry_run: bool = typer.Option(False, "--dry-run", help=_("container.flag.dry_run")),
    json_output: bool = typer.Option(False, "--json", help=_("flag.json")),
) -> None:
    tool = containers_core.find_container_tool()
    if not tool:
        output.fail(_("container.no_tool"))
        return
    command = [tool, "run", "--rm"]
    if gpus:
        command += ["--gpus", gpus]
    command.append(image)
    command += [str(a) for a in ctx.args]

    if dry_run:
        output.echo(f"[bold]{_('replay.dry_title')}[/bold]")
        output.echo(f"  command: {' '.join(command)}")
        return

    run_name = image.split("/")[-1].replace(":", "-")
    record = runs.start_run(
        state.cfg(), name=run_name, command=command, backend="container", kind="container",
        extra={"image": image, "gpus": gpus},
    )
    if output.wants_json(json_output):
        output.echo_json(record.to_dict())
        return
    output.echo(f"[green]{_('container.started', id=record.run_id)}[/green]")
    output.echo(f"  [dim]{_('sim.run.watch', id=record.run_id)}[/dim]")
