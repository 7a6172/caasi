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
from .run_cmd import _require_run, _status_style, run_logs

app = typer.Typer(no_args_is_help=True)

_CHECK_SECTIONS = ["isaac", "nvidia", "hardware", "storage"]


def _sim_launch(
    ctx: typer.Context,
    config_path: Path,
    name: Optional[str],
    dry_run: bool,
    json_output: bool,
    force_headless: bool = False,
) -> None:
    cfg = state.cfg()
    try:
        exp = experiment.load_experiment(config_path)
    except experiment.ExperimentError as exc:
        output.fail(str(exc))
        return
    extra_args = list(ctx.args)
    if force_headless:
        extra_args = ["--headless", "--no-window", *extra_args]
    try:
        command, env = experiment.build_command(exp, cfg, extra_args=extra_args)
    except experiment.ExperimentError as exc:
        output.fail(str(exc))
        return

    if exp.backend != "sim" and not output.wants_json(json_output):
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
        extra={
            "experiment": str(exp.config_path),
            "headless": exp.headless or force_headless,
        },
    )
    if output.wants_json(json_output):
        output.echo_json(record.to_dict())
        return
    output.echo(f"[green]{_('sim.run.started', id=record.run_id)}[/green]")
    output.echo(f"  [dim]{_('sim.run.watch', id=record.run_id)}[/dim]")


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
    json_output: bool = typer.Option(False, "--json", help=_("flag.json")),
) -> None:
    _sim_launch(ctx, config_path, name, dry_run, json_output)


@app.command(
    "headless",
    help=_("sim.headless_help"),
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
)
def sim_headless(
    ctx: typer.Context,
    config_path: Path = typer.Argument(..., help=_("sim.run.config_help")),
    name: Optional[str] = typer.Option(None, "--name", help=_("sim.run.name_help")),
    dry_run: bool = typer.Option(False, "--dry-run", help=_("sim.run.dry_run_help")),
    json_output: bool = typer.Option(False, "--json", help=_("flag.json")),
) -> None:
    _sim_launch(ctx, config_path, name, dry_run, json_output, force_headless=True)


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
    table = Table(header_style="bold", **output.table_styles())
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


@app.command("logs", help=_("sim.logs_help"))
def sim_logs(
    query: str = typer.Argument(..., help=_("run.arg.query")),
    lines: int = typer.Option(50, "--lines", "-n", help=_("run.flag.lines")),
    follow: bool = typer.Option(False, "--follow", "-f", help=_("run.flag.follow")),
    stream: str = typer.Option("stdout", "--stream", "-s", help=_("run.flag.stream")),
) -> None:
    record = _require_run(query)
    if record.backend != "sim":
        output.fail(_("sim.logs.wrong_backend", backend=record.backend))
        return
    run_logs(query, lines=lines, follow=follow, stream=stream)


_EXTENSION_DIRS = (
    "exts",
    "extscache",
    "extsInternal",
    "extsUser",
    "extsDeprecated",
    "extsPhysics",
)


def _scan_extension_toml(path: Path) -> dict:
    """Pick the two keys we care about out of an ``extension.toml`` (no TOML dep)."""
    info: dict = {"name": None, "preload": False}
    section = None
    try:
        content = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return info
    for line in content.splitlines():
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            section = stripped[1:-1].strip()
        elif "=" in stripped and not stripped.startswith("#"):
            key, _, value = stripped.partition("=")
            value = value.split("#", 1)[0].strip().strip("\"'")
            if section == "package" and key.strip() == "name" and not info["name"]:
                info["name"] = value
            elif section == "core" and key.strip() == "preload":
                info["preload"] = value.lower() == "true"
    return info


@app.command("extensions", help=_("sim.extensions_help"))
def sim_extensions(
    enabled: bool = typer.Option(False, "--enabled", help=_("sim.extensions.enabled_help")),
    user: bool = typer.Option(False, "--user", help=_("sim.extensions.user_help")),
    json_output: bool = typer.Option(False, "--json", help=_("flag.json")),
) -> None:
    resolved = state.cfg().resolve_tool("isaacsim")
    root = resolved.expanded_path if resolved else None
    if root is None or not root.is_dir():
        output.fail(_("sim.status.unresolved"))
        return
    entries = []
    for dirname in (("extsUser",) if user else _EXTENSION_DIRS):
        base = root / dirname
        if not base.is_dir():
            continue
        for toml_path in sorted(base.glob("*/config/extension.toml")):
            info = _scan_extension_toml(toml_path)
            if enabled and not info["preload"]:
                continue
            entries.append(
                {
                    "name": info["name"] or toml_path.parent.parent.name,
                    "source": dirname,
                    "enabled": info["preload"],
                }
            )
    if output.wants_json(json_output):
        output.echo_json(entries)
        return
    if not entries:
        output.echo(f"[dim]{_('sim.extensions.none')}[/dim]")
        return
    table = Table(header_style="bold", **output.table_styles())
    table.add_column(_("sim.extensions.col.name"))
    table.add_column(_("sim.extensions.col.source"))
    table.add_column(_("sim.extensions.col.enabled"))
    for entry in entries:
        table.add_row(entry["name"], entry["source"], "✓" if entry["enabled"] else "—")
    output.echo(table)


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
