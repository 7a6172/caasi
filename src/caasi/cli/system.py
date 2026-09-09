"""`caasi system` — OS / CPU / RAM / process overview."""

from __future__ import annotations

import os
import platform
from pathlib import Path

import typer
from rich.table import Table

from .. import state
from ..checks import run_checks
from ..core import nvidia
from ..i18n import _
from ..utils import output, shell, sysinfo
from . import ecosystem as eco

app = typer.Typer(no_args_is_help=True)

DOCTOR_SECTIONS = ["system", "hardware", "storage"]


def _os_summary() -> dict:
    uname = platform.uname()
    meminfo = sysinfo.read_meminfo()
    total_kib = meminfo.get("MemTotal", 0)
    available_kib = meminfo.get("MemAvailable", 0)
    gpu_count: int | None = None
    if nvidia.available():
        try:
            gpu_count = len(nvidia.query(["index", "name"]))
        except nvidia.NvidiaSmiError:
            gpu_count = None
    disk = sysinfo.disk_usage(Path.home())
    return {
        "os": sysinfo.os_pretty_name() or uname.system,
        "kernel": uname.release,
        "arch": uname.machine,
        "cpu": sysinfo.cpu_model(),
        "cores": os.cpu_count(),
        "load": sysinfo.load_average(),
        "ram_total_gib": round(total_kib / (1024 * 1024), 1),
        "ram_available_gib": round(available_kib / (1024 * 1024), 1),
        "gpu_count": gpu_count,
        "disk_free_home": sysinfo.human_bytes(disk.free) if disk else None,
    }


@app.command("status")
def system_status(json_output: bool = typer.Option(False, "--json", help=_("flag.json"))) -> None:
    data = _os_summary()
    if output.wants_json(json_output):
        output.echo_json(data)
        return

    table = Table(header_style="bold", show_header=False, **output.table_styles())
    table.add_column(style="bold")
    table.add_column()
    load = ", ".join(f"{x:.2f}" for x in data["load"]) if data["load"] else "n/a"
    for label, value in (
        (_("system.row.os"), f"{data['os']} ({data['arch']})"),
        (_("system.row.kernel"), data["kernel"]),
        (_("system.row.cpu"), f"{data['cpu'] or 'n/a'} ({data['cores']} cores)"),
        (_("system.row.load"), load),
        (
            _("system.row.ram"),
            f"{data['ram_available_gib']} / {data['ram_total_gib']} GiB " + _("system.row.ram_suffix"),
        ),
        (_("system.row.gpu"), str(data["gpu_count"]) if data["gpu_count"] is not None else "n/a"),
        (_("system.row.disk"), data["disk_free_home"] or "n/a"),
    ):
        table.add_row(label, str(value))
    output.echo(table)


@app.command("doctor")
def system_doctor(
    verbose: bool = typer.Option(False, "--verbose", help=_("doctor.flag.verbose")),
    json_output: bool = typer.Option(False, "--json", help=_("flag.json")),
) -> None:
    results = run_checks(DOCTOR_SECTIONS, state.cfg())
    eco.render_checks(
        {"group": "system", "sections": DOCTOR_SECTIONS}, results, verbose, json_output
    )


@app.command("memory")
def system_memory(json_output: bool = typer.Option(False, "--json", help=_("flag.json"))) -> None:
    meminfo = sysinfo.read_meminfo()
    if not meminfo:
        output.fail(_("system.no_meminfo"))
        return

    def gib(key: str) -> float:
        return round(meminfo.get(key, 0) / (1024 * 1024), 2)

    data = {
        "total_gib": gib("MemTotal"),
        "available_gib": gib("MemAvailable"),
        "free_gib": gib("MemFree"),
        "buffers_gib": gib("Buffers"),
        "cached_gib": gib("Cached"),
        "swap_total_gib": gib("SwapTotal"),
        "swap_free_gib": gib("SwapFree"),
    }
    if output.wants_json(json_output):
        output.echo_json(data)
        return

    table = Table(header_style="bold", show_header=False, **output.table_styles())
    table.add_column(style="bold")
    table.add_column(justify="right")
    for label, key in (
        (_("system.mem.total"), "total_gib"),
        (_("system.mem.available"), "available_gib"),
        (_("system.mem.free"), "free_gib"),
        (_("system.mem.buffers"), "buffers_gib"),
        (_("system.mem.cached"), "cached_gib"),
        (_("system.mem.swap"), "swap_total_gib"),
        (_("system.mem.swap_free"), "swap_free_gib"),
    ):
        table.add_row(label, f"{data[key]:.2f} GiB")
    output.echo(table)


@app.command("processes")
def system_processes(
    limit: int = typer.Option(10, "--limit", "-n", help=_("system.flag.limit")),
    json_output: bool = typer.Option(False, "--json", help=_("flag.json")),
) -> None:
    ps = shell.which("ps")
    rows: list[tuple[str, str, str, str]] = []
    if ps:
        result = shell.run_cmd(["ps", "-eo", "pid,user,pmem,rss,comm", "--sort=-rss"], timeout=10)
        if result.ok:
            for line in result.stdout.splitlines()[1 : limit + 1]:
                parts = line.split(None, 4)
                if len(parts) == 5:
                    pid, user, pmem, rss, comm = parts
                    rows.append((pid, user, pmem, f"{int(rss) / 1024:.0f} MiB", comm))
    if not rows:
        for proc in sysinfo.top_processes(limit):
            rows.append((str(proc.pid), "?", "?", f"{proc.rss_kb / 1024:.0f} MiB", proc.command))

    if output.wants_json(json_output):
        output.echo_json(
            [
                {"pid": r[0], "user": r[1], "mem_percent": r[2], "rss": r[3], "command": r[4]}
                for r in rows
            ]
        )
        return

    table = Table(header_style="bold", **output.table_styles())
    for column in ("PID", _("system.col.user"), _("system.col.mem"), _("system.col.rss"), _("system.col.command")):
        table.add_column(column)
    for row in rows:
        table.add_row(*row)
    output.echo(table)


if __name__ == "__main__":  # pragma: no cover
    app()
