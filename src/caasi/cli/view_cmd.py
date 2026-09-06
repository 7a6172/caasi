"""`caasi view` — visualize runs by orchestrating existing viewers."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import typer

from ..core import runs
from ..core import viewers as viewers_core
from ..i18n import _
from ..utils import output
from .run_cmd import _require_run

app = typer.Typer(no_args_is_help=True)


def _require_viewer(name: str) -> str:
    binary = viewers_core.viewer_binary(name)
    if not binary:
        output.fail(
            _("view.not_found", viewer=name, hint=_(f"view.hint.{name}"))
        )
        raise typer.Exit(1)  # unreachable, keeps type-checkers happy
    return binary


def _launch_or_show(name: str, command: list[str], dry_run: bool) -> None:
    if dry_run:
        output.echo(f"[bold]{_('replay.dry_title')}[/bold]")
        output.echo(f"  command: {' '.join(command)}")
        return
    pid = viewers_core.launch(command)
    output.echo(f"[green]{_('view.started', viewer=name, pid=pid)}[/green]")


@app.command("rviz", help=_("view.rviz_help"))
def view_rviz(
    config_file: Optional[Path] = typer.Argument(None, help=_("view.arg.config")),
    dry_run: bool = typer.Option(False, "--dry-run", help=_("view.flag.dry_run")),
) -> None:
    binary = _require_viewer("rviz")
    command = [binary, *(["-d", str(config_file)] if config_file else [])]
    _launch_or_show("rviz", command, dry_run)


@app.command("foxglove", help=_("view.foxglove_help"))
def view_foxglove(
    dry_run: bool = typer.Option(False, "--dry-run", help=_("view.flag.dry_run")),
) -> None:
    binary = _require_viewer("foxglove")
    _launch_or_show("foxglove", [binary], dry_run)


@app.command("open3d", help=_("view.open3d_help"))
def view_open3d(
    target: Path = typer.Argument(..., help=_("view.arg.target")),
    dry_run: bool = typer.Option(False, "--dry-run", help=_("view.flag.dry_run")),
) -> None:
    binary = _require_viewer("open3d")
    if not target.exists():
        output.fail(_("view.path_missing", path=str(target)))
        return
    command = viewers_core.viewer_command("open3d", binary, target)
    _launch_or_show("open3d", command, dry_run)


@app.command("attach", help=_("view.attach_help"))
def view_attach(
    query: str = typer.Argument(..., help=_("run.arg.query")),
    viewer: Optional[str] = typer.Option(None, "--viewer", help=_("view.flag.viewer")),
    dry_run: bool = typer.Option(False, "--dry-run", help=_("view.flag.dry_run")),
) -> None:
    record = _require_run(query)
    status = runs.effective_status(record)
    if status not in (runs.RUNNING, runs.PAUSED):
        output.fail(_("view.not_active", id=record.run_id, status=status))
        return
    if viewer and viewer not in viewers_core.VIEWER_NAMES:
        output.fail(_("replay.bad_viewer", viewer=viewer))
        return
    name, binary = viewers_core.find_viewer(viewer)
    if not name or not binary:
        output.fail(_("replay.no_viewer"))
        return
    command = viewers_core.viewer_command(name, binary)
    if dry_run:
        output.echo(f"[bold]{_('replay.dry_title')}[/bold]")
        output.echo(f"  command: {' '.join(command)}")
        return
    pid = viewers_core.launch(command, {"CAASI_RUN_DIR": str(record.directory)})
    output.echo(f"[green]{_('view.started', viewer=name, pid=pid)}[/green]")
