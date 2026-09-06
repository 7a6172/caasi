"""`caasi sim` — run and control Isaac Sim experiments (headless by default)."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import typer
from rich.table import Table

from .. import state
from ..checks import SECTION_KEYS, run_checks
from ..core import experiment, runs
from ..i18n import _
from ..utils import output
from .run_cmd import _require_run, _status_style

app = typer.Typer(no_args_is_help=True)

_CHECK_SECTIONS = ["isaac", "nvidia", "hardware", "storage"]


@app.command(
    "run",
    help=_("sim.run_help"),
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
)
def sim_run(
    ctx: typer.Context,
    config_path: Path = typer.Argument(..., help=_("sim.run.config_help")),
    name: Optional[str] = typer.Option(None, "--name", help=_("sim.run.name_help")),
    dry_run: bool = typer.Option(False, "--dry-run", help=_("sim.run.dry_run_help")),
) -> None:
    cfg = state.cfg()
    try:
        exp = experiment.load_experiment(config_path)
    except experiment.ExperimentError as exc:
        output.fail(str(exc))
        return
    try:
        command, env = experiment.build_command(exp, cfg, extra_args=list(ctx.args))
    except experiment.ExperimentError as exc:
        output.fail(str(exc))
        return

    if exp.backend != "sim":
        output.echo(
            f"[yellow]{_('sim.run.backend_note', backend=exp.backend)}[/yellow]"
        )

    if dry_run:
        output.echo(f"[bold]{_('sim.run.dry_title')}[/bold]")
        output.echo(f"  command: {' '.join(command)}")
        output.echo(f"  cwd:     {exp.work_dir}")
        for key in sorted(env):
            if key in exp.env or key.startswith("ISAAC"):
                output.echo(f"  env:     {key}={env[key]}")
        return

    record = runs.start_run(
        cfg,
        name=name or exp.name,
        command=command,
        cwd=exp.work_dir,
        env=env,
        backend=exp.backend,
        kind="experiment",
        extra={"experiment": str(exp.config_path), "headless": exp.headless},
    )
    if output.wants_json(False):
        output.echo_json(record.to_dict())
        return
    output.echo(f"[green]{_('sim.run.started', id=record.run_id)}[/green]")
    output.echo(f"  [dim]{_('sim.run.watch', id=record.run_id)}[/dim]")


@app.command("status", help=_("sim.status_help"))
def sim_status(json_output: bool = typer.Option(False, "--json", help=_("flag.json"))) -> None:
    cfg = state.cfg()
    resolved = cfg.resolve_tool("isaacsim")
    active = [
        r
        for r in runs.list_runs(cfg)
        if r.backend == "sim"
        and runs.effective_status(r) in (runs.RUNNING, runs.PAUSED)
    ]
    payload = {
        "backend": {
            "tool": "isaacsim",
            "version": resolved.version if resolved else None,
            "path": resolved.path if resolved else None,
            "python": resolved.python if resolved else None,
        },
        "active_runs": [r.to_dict() for r in active],
    }
    if output.wants_json(json_output):
        output.echo_json(payload)
        return

    if resolved:
        output.echo(
            f"[green]✓[/green] Isaac Sim [bold]{resolved.version or '?'}[/bold] → {resolved.path}"
        )
    else:
        output.echo(f"[red]✗[/red] { _('sim.status.unresolved') }")

    if not active:
        output.echo(f"[dim]{_('sim.status.no_active')}[/dim]")
        return
    table = Table(title=_("sim.status.active_title"), header_style="bold")
    for column in ("ID", _("run.col.name"), _("run.col.status"), "PID"):
        table.add_column(column)
    for record in active:
        status = runs.effective_status(record)
        table.add_row(
            record.run_id,
            record.name,
            f"[{_status_style(status)}]{status}[/]",
            str(record.pid) if record.pid else "—",
        )
    output.echo(table)


@app.command("check", help=_("sim.check_help"))
def sim_check(verbose: bool = typer.Option(False, "--verbose", help=_("sim.check.verbose_help"))) -> None:
    valid = [s for s in _CHECK_SECTIONS if s in SECTION_KEYS]
    results = run_checks(valid)
    exit_code = 1 if any(r.status == "fail" for r in results) else 0
    for result in results:
        symbol, style = output.status_symbol(result.status)
        detail = f" — {result.detail}" if result.detail else ""
        output.echo(f"[{style}]{symbol}[/] {result.name}{detail}")
        if result.hint and (verbose or result.status in ("fail", "warn")):
            output.echo(f"    [dim]↳ {result.hint}[/dim]")
    raise typer.Exit(exit_code)


def _run_action(query: str, action: str) -> None:
    record = _require_run(query)
    if action == "stop":
        ok = runs.stop_run(record)
        msg = _("run.stopped", id=record.run_id) if ok else _("run.stop_failed", id=record.run_id)
    elif action == "pause":
        ok = runs.pause_run(record)
        msg = _("run.paused", id=record.run_id) if ok else _("run.not_running", id=record.run_id, status=runs.effective_status(record))
    else:  # resume
        ok = runs.resume_run(record)
        msg = _("run.resumed", id=record.run_id) if ok else _("run.not_paused", id=record.run_id, status=runs.effective_status(record))
    if ok:
        output.echo(msg)
    else:
        output.fail(msg)


@app.command("stop", help=_("sim.stop_help"))
def sim_stop(query: str = typer.Argument(..., help=_("run.arg.query"))) -> None:
    _run_action(query, "stop")


@app.command("pause", help=_("sim.pause_help"))
def sim_pause(query: str = typer.Argument(..., help=_("run.arg.query"))) -> None:
    _run_action(query, "pause")


@app.command("resume", help=_("sim.resume_help"))
def sim_resume(query: str = typer.Argument(..., help=_("run.arg.query"))) -> None:
    _run_action(query, "resume")
