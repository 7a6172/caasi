"""`caasi replay` — replay recorded runs without rerunning the simulation."""

from __future__ import annotations

from typing import Optional

import typer

from .. import state
from ..core import runs
from ..core import viewers as viewers_core
from ..i18n import _
from ..utils import output
from .run_cmd import _require_run


def replay_command(
    query: str = typer.Argument(..., help=_("run.arg.query")),
    speed: float = typer.Option(1.0, "--speed", help=_("replay.flag.speed")),
    episode: Optional[int] = typer.Option(None, "--episode", help=_("replay.flag.episode")),
    viewer: Optional[str] = typer.Option(None, "--viewer", help=_("replay.flag.viewer")),
    dry_run: bool = typer.Option(False, "--dry-run", help=_("replay.flag.dry_run")),
    json_output: bool = typer.Option(False, "--json", help=_("flag.json")),
) -> None:
    record = _require_run(query)
    assert record.directory is not None
    artifacts = viewers_core.recorded_artifacts(record.directory)
    if not artifacts:
        output.fail(_("replay.no_data", id=record.run_id))
        return

    if viewer and viewer not in viewers_core.VIEWER_NAMES:
        output.fail(_("replay.bad_viewer", viewer=viewer))
        return
    name, binary = viewers_core.find_viewer(viewer)
    if not name or not binary:
        output.fail(_("replay.no_viewer"))
        return

    target = None
    if name == "open3d":
        target = viewers_core.find_3d_file(artifacts)
        if target is None:
            output.fail(_("replay.no_3d", id=record.run_id))
            return
    command = viewers_core.viewer_command(name, binary, target)

    env = {
        "CAASI_RUN_DIR": str(record.directory),
        "CAASI_REPLAY_SPEED": str(speed),
    }
    if episode is not None:
        env["CAASI_REPLAY_EPISODE"] = str(episode)

    payload = {
        "id": record.run_id,
        "viewer": name,
        "command": command,
        "artifacts": [str(a.relative_to(record.directory)) for a in artifacts],
    }
    if output.wants_json(json_output):
        if not dry_run:
            payload["pid"] = viewers_core.launch(command, env)
        output.echo_json(payload)
        return

    output.echo(f"[bold]{record.name}[/bold] [dim]({record.run_id})[/dim]")
    output.echo(f"  [bold]{_('replay.artifacts')}[/bold] "
                + ", ".join(payload["artifacts"]))
    if dry_run:
        output.echo(f"[bold]{_('replay.dry_title')}[/bold]")
        output.echo(f"  command: {' '.join(command)}")
        return
    pid = viewers_core.launch(command, env)
    output.echo(f"[green]{_('replay.started', viewer=name, pid=pid)}[/green]")
