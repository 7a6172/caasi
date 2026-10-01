"""``caasi monitor`` — the Layer 7 door (§5.4).

A ``rich.live`` follow of the machine + run collector (`gpu monitor`
pattern); ``--once``/``--json`` print a single snapshot — the honest
replacement for the dropped root ``status``. ``gpu monitor`` stays
GPU-only; ``system status/memory/processes`` stay machine-only.
"""

from __future__ import annotations

from typing import Optional

import typer
from rich.console import Group
from rich.live import Live
from rich.table import Table

from .. import state
from ..core import monitor, runs
from ..core.config import Config
from ..i18n import _
from ..utils import output, sysinfo
from . import run_cmd


def _fmt(value: Optional[float], suffix: str = "") -> str:
    return "?" if value is None else f"{value:.1f}{suffix}"


def _hms(seconds: Optional[float]) -> str:
    if seconds is None:
        return "?"
    total = int(seconds)
    hours, rest = divmod(total, 3600)
    minutes, secs = divmod(rest, 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


def _resolve(query: Optional[str]) -> tuple[Optional[runs.RunRecord], Config]:
    """Default to the latest run; degrade to machine-only when none exist."""
    config = state.cfg()
    if query is None:
        all_runs = runs.list_runs(config)
        return (all_runs[0] if all_runs else None), config
    record = runs.find_run(config, query)
    if record is None:
        output.fail(_("run.not_found", query=query))
        raise typer.Exit(1)  # unreachable, keeps type-checkers happy
    return record, config


def _render(record: Optional[runs.RunRecord], snap: monitor.Sample) -> Group:
    metrics = Table(header_style="bold", **output.table_styles())
    metrics.add_column(_("monitor.col.metric"))
    metrics.add_column(_("monitor.col.value"))
    if record is not None:
        status = runs.effective_status(record)
        metrics.add_row(_("monitor.row.run"), f"{record.name} [dim]({record.run_id})[/dim]")
        metrics.add_row(
            _("monitor.row.status"), f"[{run_cmd._status_style(status)}]{status}[/]"
        )
    metrics.add_row(_("monitor.row.cpu"), _fmt(snap.cpu, "%"))
    ram = (
        f"{snap.ram_used:.1f} / {snap.ram_total:.1f} GiB"
        if snap.ram_used is not None and snap.ram_total is not None
        else "?"
    )
    metrics.add_row(_("monitor.row.ram"), ram)
    metrics.add_row(_("monitor.row.gpu"), _fmt(snap.gpu, "%"))
    vram = (
        f"{snap.vram_used:.1f} / {snap.vram_total:.1f} GiB"
        if snap.vram_used is not None and snap.vram_total is not None
        else "?"
    )
    metrics.add_row(_("monitor.row.vram"), vram)
    if snap.steps_per_s is not None:  # §4.6: omitted when absent
        metrics.add_row(
            _("monitor.row.simulation"),
            f"{snap.steps_per_s:.1f} {_('monitor.steps_unit')}",
        )
    metrics.add_row(_("monitor.row.runtime"), _hms(snap.runtime_s))

    panels: list = [metrics]
    if snap.processes:
        procs = Table(
            title=_("monitor.processes_title"), header_style="bold", **output.table_styles()
        )
        procs.add_column(_("monitor.col.pid"))
        procs.add_column(_("monitor.col.rss"))
        procs.add_column(_("monitor.col.command"))
        for proc in snap.processes:
            procs.add_row(
                str(proc.pid), sysinfo.human_bytes(proc.rss_kb * 1024), proc.command
            )
        panels.append(procs)
    return Group(*panels)


def _payload(record: Optional[runs.RunRecord], snap: monitor.Sample) -> dict:
    data: dict = {
        "run": record.run_id if record else None,
        "name": record.name if record else None,
        "status": runs.effective_status(record) if record else None,
        "backend": record.backend if record else None,
    }
    data.update(snap.to_dict())
    return data


def monitor_command(
    query: Optional[str] = typer.Argument(None, help=_("monitor.arg.run")),
    interval: float = typer.Option(2.0, "--interval", min=0.1, help=_("monitor.flag.interval")),
    once: bool = typer.Option(False, "--once", help=_("monitor.flag.once")),
    json_output: bool = typer.Option(False, "--json", help=_("flag.json")),
) -> None:
    record, config = _resolve(query)

    if once or output.wants_json(json_output):
        snap = monitor.sample(record, config)
        if output.wants_json(json_output):
            output.echo_json(_payload(record, snap))
            return
        if record is None:
            output.echo(f"[dim]{_('monitor.no_run')}[/dim]")
        output.echo(_render(record, snap))
        return

    if record is None:
        output.echo(f"[dim]{_('monitor.no_run')}[/dim]")
    try:
        with Live(console=output.console(), refresh_per_second=4) as display:
            monitor.live(
                record,
                config,
                interval,
                lambda snap: display.update(_render(record, snap)),
            )
    except KeyboardInterrupt:
        output.echo(_("monitor.stopped"))
