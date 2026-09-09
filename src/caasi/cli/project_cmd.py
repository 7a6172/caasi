"""`caasi project` — inspect and manage Caasi projects."""

from __future__ import annotations

from pathlib import Path

import typer
from rich.table import Table

from ..core import project as projects
from ..i18n import _
from ..utils import output

app = typer.Typer(no_args_is_help=True)


def require_project() -> Path:
    root = projects.find_project_root()
    if root is None:
        output.fail(_("project.not_found"))
        raise typer.Exit(1)  # unreachable, keeps type-checkers happy
    return root


def _project_payload(root: Path) -> dict:
    meta = projects.load_project_meta(root)
    counts = {
        kind: len(projects.list_definitions(root, kind))
        for kind in projects.COMPONENT_KINDS
    }
    experiments = root / "experiments"
    counts["experiments"] = (
        len(list(experiments.glob("*.yaml"))) if experiments.is_dir() else 0
    )
    return {"root": str(root), "name": meta.get("name", ""), "counts": counts}


@app.command("info", help=_("project.info_help"))
def project_info(json_output: bool = typer.Option(False, "--json", help=_("flag.json"))) -> None:
    root = require_project()
    payload = _project_payload(root)
    if output.wants_json(json_output):
        output.echo_json(payload)
        return
    table = Table(header_style="bold", show_header=False, **output.table_styles())
    table.add_column(style="bold")
    table.add_column()
    table.add_row(_("project.row.root"), payload["root"])
    table.add_row(_("project.row.name"), payload["name"] or "—")
    table.add_row(_("project.row.robots"), str(payload["counts"]["robot"]))
    table.add_row(_("project.row.scenes"), str(payload["counts"]["scene"]))
    table.add_row(_("project.row.tasks"), str(payload["counts"]["task"]))
    table.add_row(_("project.row.experiments"), str(payload["counts"]["experiments"]))
    output.echo(table)


@app.command("validate", help=_("project.validate_help"))
def project_validate() -> None:
    root = require_project()
    issues = projects.validate_project(root)
    if not issues:
        output.echo(f"[green]{_('project.valid', path=str(root))}[/green]")
        return
    output.echo(f"[red]{_('project.issues', count=len(issues))}[/red]")
    for issue in issues:
        output.echo(f"  [red]✗[/red] {issue}")
    raise typer.Exit(1)
