"""`caasi container` — run experiments inside official container images.

caasi detects Docker/Podman, lists Isaac images and builds `docker run`
commands; the runtime does the actual work.
"""

from __future__ import annotations

from pathlib import Path

import typer

from .. import state
from ..checks import CheckResult, run_checks
from ..core import containers as containers_core
from ..core import runs
from ..i18n import _
from ..utils import output
from . import ecosystem as eco

app = typer.Typer(no_args_is_help=True)

DOCTOR_SECTIONS = ["containers", "nvidia"]

_EXTRA_SETTINGS = {"allow_extra_args": True, "ignore_unknown_options": True}


def _runtime_state() -> dict:
    """Tool / daemon / NVIDIA-runtime facts, all from ``core.containers``."""
    tool = containers_core.find_container_tool()
    daemon = containers_core.daemon_ok(tool) if tool else False
    gpu = containers_core.nvidia_runtime(tool) if tool and daemon else False
    local = containers_core.local_images(tool) if tool and daemon else []
    return {
        "tool": tool,
        "daemon": daemon,
        "nvidia_runtime": gpu,
        "known": [entry["image"] for entry in containers_core.KNOWN_IMAGES],
        "local": local,
    }


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


@app.command("status", help=_("container.status_help"))
def container_status(
    json_output: bool = typer.Option(False, "--json", help=_("flag.json")),
) -> None:
    info = _runtime_state()
    if output.wants_json(json_output):
        output.echo_json({**info, "ready": bool(info["tool"] and info["daemon"])})
        return
    output.echo(f"[bold]{_('container.title')}[/bold]")
    rows = (
        (
            _("container.row.runtime_tool"),
            Path(info["tool"]).name if info["tool"] else _("container.missing"),
        ),
        (
            _("container.row.daemon"),
            _("container.daemon_ok") if info["daemon"] else _("container.daemon_fail"),
        ),
        (
            _("container.row.nvidia"),
            _("container.gpu_ok") if info["nvidia_runtime"] else _("container.gpu_fail"),
        ),
        (_("container.row.known"), str(len(info["known"]))),
        (
            _("container.row.local"),
            ", ".join(info["local"]) if info["local"] else _("container.no_local"),
        ),
    )
    for label, value in rows:
        output.echo(f"  {label:<16} {value}")
    if not info["tool"]:
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


def _doctor_extras() -> list[CheckResult]:
    """GPU-in-container guidance, on top of the ``containers``/``nvidia`` checks."""
    info = _runtime_state()
    name = _("container.doctor.gpu")
    if not info["tool"]:
        return [CheckResult("containers", name, "skip", _("container.no_tool"))]
    if not info["daemon"]:
        return [CheckResult("containers", name, "skip", _("container.daemon_fail"))]
    if info["nvidia_runtime"]:
        return [
            CheckResult("containers", name, "ok", _("container.gpu_ok"), _("container.doctor.gpu_ok_hint"))
        ]
    return [
        CheckResult("containers", name, "warn", _("container.gpu_fail"), _("container.doctor.gpu_hint"))
    ]


@app.command("doctor", help=_("container.doctor_help"))
def container_doctor(
    verbose: bool = typer.Option(False, "--verbose", help=_("doctor.flag.verbose")),
    json_output: bool = typer.Option(False, "--json", help=_("flag.json")),
) -> None:
    results = run_checks(DOCTOR_SECTIONS, state.cfg())
    results.extend(_doctor_extras())
    eco.render_checks(
        {"group": "container", "sections": DOCTOR_SECTIONS}, results, verbose, json_output
    )


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
