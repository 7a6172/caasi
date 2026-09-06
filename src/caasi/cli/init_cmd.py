"""`caasi init` — create a new Caasi project scaffold."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import typer

from ..core import project as projects
from ..i18n import _
from ..utils import output


def init_command(
    path: Path = typer.Argument(Path("."), help=_("init.arg.path")),
    name: Optional[str] = typer.Option(None, "--name", help=_("init.flag.name")),
    force: bool = typer.Option(False, "--force", help=_("init.flag.force")),
    json_output: bool = typer.Option(False, "--json", help=_("flag.json")),
) -> None:
    try:
        root = projects.create_project(Path(path), name=name, force=force)
    except projects.ProjectError as exc:
        output.fail(str(exc))
        return

    meta = projects.load_project_meta(root)
    payload = {"root": str(root), "name": meta.get("name"), "dirs": list(projects.PROJECT_DIRS)}
    if output.wants_json(json_output):
        output.echo_json(payload)
        return

    output.echo(f"[green]{_('init.done', name=payload['name'], path=str(root))}[/green]")
    output.echo(f"  {projects.PROJECT_FILE}")
    for sub in projects.PROJECT_DIRS:
        output.echo(f"  [dim]{sub}/[/dim]")
    output.echo(f"  [dim]{_('init.hint')}[/dim]")
