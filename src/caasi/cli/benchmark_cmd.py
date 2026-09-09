"""`caasi benchmark` — measure simulation performance without a viewport."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import typer
from rich.table import Table

from .. import state
from ..core import benchmark as benchmark_core
from ..core import experiment, runs
from ..i18n import _
from ..utils import output
from .run_cmd import _require_run

app = typer.Typer(no_args_is_help=True)


@app.command(
    "start",
    help=_("benchmark.start_help"),
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
)
def benchmark_start(
    ctx: typer.Context,
    config_path: Path = typer.Argument(..., help=_("benchmark.arg.config")),
    envs: Optional[int] = typer.Option(None, "--envs", help=_("benchmark.flag.envs")),
    steps: Optional[int] = typer.Option(None, "--steps", help=_("benchmark.flag.steps")),
    dry_run: bool = typer.Option(False, "--dry-run", help=_("benchmark.flag.dry_run")),
) -> None:
    cfg = state.cfg()
    try:
        exp = experiment.load_experiment(config_path)
    except experiment.ExperimentError as exc:
        output.fail(str(exc))
        return
    extra: list[str] = []
    if envs is not None:
        extra += ["--envs", str(envs)]
    if steps is not None:
        extra += ["--steps", str(steps)]
    if exp.headless:
        extra.append("--headless")
    extra += list(ctx.args)
    try:
        command, env = experiment.build_command(exp, cfg, extra_args=extra)
    except experiment.ExperimentError as exc:
        output.fail(str(exc))
        return

    if dry_run:
        output.echo(f"[bold]{_('sim.run.dry_title')}[/bold]")
        output.echo(f"  command: {' '.join(command)}")
        output.echo(f"  cwd:     {exp.work_dir}")
        return

    record = runs.start_run(
        cfg,
        name=exp.name,
        command=command,
        cwd=exp.work_dir,
        env=env,
        backend=exp.backend,
        kind="benchmark",
        extra={"experiment": str(exp.config_path), "envs": envs, "steps": steps},
    )
    output.echo(f"[green]{_('sim.run.started', id=record.run_id)}[/green]")
    output.echo(f"  [dim]{_('benchmark.report_hint', id=record.run_id)}[/dim]")


@app.command("report", help=_("benchmark.report_help"))
def benchmark_report(
    query: str = typer.Argument(..., help=_("run.arg.query")),
    json_output: bool = typer.Option(False, "--json", help=_("flag.json")),
) -> None:
    record = _require_run(query)
    status = runs.effective_status(record)
    path = runs.log_path(record, "stdout")
    text = ""
    if path is not None:
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            text = ""
    metrics = benchmark_core.parse_metrics(text)

    payload = {
        "id": record.run_id,
        "status": status,
        "metrics": metrics,
    }
    if output.wants_json(json_output):
        output.echo_json(payload)
        raise typer.Exit(1 if status == runs.TERMINAL_FAIL else 0)

    output.echo(
        f"[bold]{record.name}[/bold] [dim]({record.run_id})[/dim] — {status}"
    )
    if status in (runs.RUNNING, runs.PAUSED):
        output.echo(f"  [yellow]{_('benchmark.still_running')}[/yellow]")
    if not metrics:
        output.echo(f"  [dim]{_('benchmark.no_metrics')}[/dim]")
        raise typer.Exit(1 if status == runs.TERMINAL_FAIL else 0)
    table = Table(header_style="bold", **output.table_styles())
    table.add_column(_("benchmark.col.metric"))
    table.add_column(_("benchmark.col.value"), justify="right")
    for key, value in metrics.items():
        table.add_row(key, f"{value:g}")
    output.echo(table)
