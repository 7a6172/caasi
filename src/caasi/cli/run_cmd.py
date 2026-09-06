"""`caasi run` — manage simulation runs as first-class processes."""

from __future__ import annotations

import time

import typer
from rich.table import Table

from .. import state
from ..core import runs
from ..i18n import _
from ..utils import output

app = typer.Typer(no_args_is_help=True)


def _require_run(query: str) -> runs.RunRecord:
    record = runs.find_run(state.cfg(), query)
    if record is None:
        output.fail(_("run.not_found", query=query))
        raise typer.Exit(1)  # unreachable, keeps type-checkers happy
    return record


def _status_style(status: str) -> str:
    return {
        runs.TERMINAL_OK: "green",
        runs.TERMINAL_FAIL: "red",
        runs.RUNNING: "cyan",
        runs.PAUSED: "yellow",
        runs.STOPPED: "dim",
        runs.LOST: "magenta",
    }.get(status, "white")


@app.command("list", help=_("run.list_help"))
def run_list(
    limit: int = typer.Option(20, "--limit", "-n", help=_("run.flag.limit")),
    json_output: bool = typer.Option(False, "--json", help=_("flag.json")),
) -> None:
    records = runs.list_runs(state.cfg())[: max(limit, 0)]
    if output.wants_json(json_output):
        output.echo_json([r.to_dict() for r in records])
        return
    if not records:
        output.echo(f"[yellow]{_('run.no_runs')}[/yellow]")
        return
    table = Table(title=_("run.list_title"), header_style="bold")
    for column in ("ID", _("run.col.name"), _("run.col.backend"), _("run.col.status"), _("run.col.created"), "PID"):
        table.add_column(column)
    for record in records:
        status = runs.effective_status(record)
        table.add_row(
            record.run_id,
            record.name,
            record.backend,
            f"[{_status_style(status)}]{status}[/]",
            record.created,
            str(record.pid) if record.pid else "—",
        )
    output.echo(table)


@app.command("status", help=_("run.status_help"))
def run_status(
    query: str = typer.Argument(..., help=_("run.arg.query")),
    json_output: bool = typer.Option(False, "--json", help=_("flag.json")),
) -> None:
    record = _require_run(query)
    data = record.to_dict()
    if output.wants_json(json_output):
        output.echo_json(data)
        return
    output.echo(f"[bold]{record.name}[/bold] [dim]({record.run_id})[/dim]")
    for label, value in (
        (_("run.col.status"), data["status"]),
        (_("run.col.backend"), record.backend),
        ("Kind", record.kind),
        (_("run.col.created"), record.created),
        ("PID", str(record.pid) if record.pid else "—"),
        ("Directory", str(record.directory)),
        ("Command", " ".join(record.command)),
    ):
        output.echo(f"  {label:<12} {value}")


@app.command("logs", help=_("run.logs_help"))
def run_logs(
    query: str = typer.Argument(..., help=_("run.arg.query")),
    lines: int = typer.Option(50, "--lines", "-n", help=_("run.flag.lines")),
    follow: bool = typer.Option(False, "--follow", "-f", help=_("run.flag.follow")),
    stream: str = typer.Option("stdout", "--stream", "-s", help=_("run.flag.stream")),
) -> None:
    record = _require_run(query)
    if stream not in ("stdout", "stderr"):
        output.fail(_("run.bad_stream", stream=stream))
        return
    path = runs.log_path(record, stream)
    if path is None:
        output.fail(_("run.no_log", stream=stream))
        return

    def tail() -> list[str]:
        try:
            content = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return []
        return content.splitlines()[-max(lines, 0):]

    for line in tail():
        output.echo(line, markup=False)

    if not follow:
        return
    try:
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            handle.seek(0, 2)
            while True:
                line = handle.readline()
                if line:
                    output.echo(line.rstrip("\n"), markup=False)
                else:
                    if runs.effective_status(record) in (
                        runs.TERMINAL_OK,
                        runs.TERMINAL_FAIL,
                        runs.STOPPED,
                    ):
                        break
                    time.sleep(0.5)
    except KeyboardInterrupt:  # pragma: no cover
        pass


@app.command("stop", help=_("run.stop_help"))
def run_stop(query: str = typer.Argument(..., help=_("run.arg.query"))) -> None:
    record = _require_run(query)
    if runs.stop_run(record):
        output.echo(_("run.stopped", id=record.run_id))
        return
    output.fail(_("run.stop_failed", id=record.run_id))


@app.command("pause", help=_("run.pause_help"))
def run_pause(query: str = typer.Argument(..., help=_("run.arg.query"))) -> None:
    record = _require_run(query)
    if runs.pause_run(record):
        output.echo(_("run.paused", id=record.run_id))
        return
    output.fail(_("run.not_running", id=record.run_id, status=runs.effective_status(record)))


@app.command("resume", help=_("run.resume_help"))
def run_resume(query: str = typer.Argument(..., help=_("run.arg.query"))) -> None:
    record = _require_run(query)
    if runs.resume_run(record):
        output.echo(_("run.resumed", id=record.run_id))
        return
    output.fail(_("run.not_paused", id=record.run_id, status=runs.effective_status(record)))


@app.command("delete", help=_("run.delete_help"))
def run_delete(
    query: str = typer.Argument(..., help=_("run.arg.query")),
    force: bool = typer.Option(False, "--force", help=_("run.flag.force")),
) -> None:
    record = _require_run(query)
    if force and runs.effective_status(record) in (runs.RUNNING, runs.PAUSED):
        runs.stop_run(record)
        record = runs.load_run(state.cfg(), record.run_id) or record
    if runs.delete_run(record):
        output.echo(_("run.deleted", id=record.run_id))
        return
    output.fail(_("run.delete_running", id=record.run_id))


@app.command("inspect", help=_("run.inspect_help"))
def run_inspect(
    query: str = typer.Argument(..., help=_("run.arg.query")),
    json_output: bool = typer.Option(False, "--json", help=_("flag.json")),
) -> None:
    record = _require_run(query)
    files = []
    if record.directory and record.directory.is_dir():
        for item in sorted(record.directory.rglob("*")):
            if item.is_file():
                files.append(
                    {"path": str(item.relative_to(record.directory)), "size": item.stat().st_size}
                )
    payload = {**record.to_dict(), "files": files}
    if output.wants_json(json_output):
        output.echo_json(payload)
        return
    output.echo(f"[bold]{record.name}[/bold] [dim]({record.run_id})[/dim]")
    output.echo(f"  Directory: {record.directory}")
    output.echo(f"  Status:    {payload['status']}")
    if not files:
        output.echo(f"  [dim]{_('run.no_files')}[/dim]")
        return
    table = Table(header_style="bold")
    table.add_column(_("run.col.file"))
    table.add_column(_("run.col.size"), justify="right")
    from ..utils.sysinfo import human_bytes

    for item in files:
        table.add_row(item["path"], human_bytes(item["size"]))
    output.echo(table)
