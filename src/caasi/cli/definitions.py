"""`caasi robot` / `caasi scene` / `caasi task` — component definitions.

All three groups share the same file-based model (``<kind>s/<name>.yaml``
inside the project), so the Typer apps are built from one factory.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import typer
import yaml
from rich.table import Table

from ..core import project as projects
from ..i18n import _
from ..utils import output


def build_app(kind: str) -> typer.Typer:
    app = typer.Typer(no_args_is_help=True)
    plural = projects.KIND_DIRS[kind]

    def _require_project() -> Path:
        root = projects.find_project_root()
        if root is None:
            output.fail(_("project.not_found"))
            raise typer.Exit(1)  # unreachable, keeps type-checkers happy
        return root

    def _require_definition(root: Path, name: str) -> dict:
        data = projects.load_definition(root, kind, name)
        if data is None:
            output.fail(_("def.not_found", kind=kind, name=name, dir=plural))
            raise typer.Exit(1)  # unreachable, keeps type-checkers happy
        return data

    @app.command("list", help=_(f"{kind}.list_help"))
    def list_definitions(
        json_output: bool = typer.Option(False, "--json", help=_("flag.json")),
    ) -> None:
        root = _require_project()
        entries = projects.list_definitions(root, kind)
        payload = [
            {
                "name": entry["name"],
                "description": entry["data"].get("description", ""),
                "path": str(entry["path"]),
            }
            for entry in entries
        ]
        if output.wants_json(json_output):
            output.echo_json(payload)
            return
        if not payload:
            output.echo(
                f"[yellow]{_('def.list_empty', kind=kind, cmd=f'caasi {kind} create')}[/yellow]"
            )
            return
        table = Table(title=_(f"{kind}.list_title"), header_style="bold")
        table.add_column(_("def.col.name"))
        table.add_column(_("def.col.description"))
        for item in payload:
            table.add_row(item["name"], item["description"] or "—")
        output.echo(table)

    @app.command("create", help=_(f"{kind}.create_help"))
    def create_definition(
        name: str = typer.Argument(..., help=_("def.arg.name")),
        description: str = typer.Option("", "--description", "-d", help=_("def.flag.description")),
    ) -> None:
        root = _require_project()
        try:
            path = projects.save_definition(root, kind, name, description=description)
        except projects.ProjectError as exc:
            output.fail(str(exc))
            return
        output.echo(f"[green]{_('def.created', kind=kind, name=name, path=str(path))}[/green]")

    @app.command("inspect", help=_(f"{kind}.inspect_help"))
    def inspect_definition(
        name: str = typer.Argument(..., help=_("def.arg.name")),
        json_output: bool = typer.Option(False, "--json", help=_("flag.json")),
    ) -> None:
        root = _require_project()
        data = _require_definition(root, name)
        if output.wants_json(json_output):
            output.echo_json(data)
            return
        output.echo(yaml.safe_dump(data, sort_keys=False).rstrip())

    if kind == "robot":

        @app.command("info", help=_("robot.info_help"))
        def robot_info(name: str = typer.Argument(..., help=_("def.arg.name"))) -> None:
            root = _require_project()
            data = _require_definition(root, name)
            sensors = data.get("sensors") or []
            tasks = data.get("tasks") or []
            output.echo(f"[bold]{data.get('name', name)}[/bold]")
            if data.get("description"):
                output.echo(f"  {data['description']}")
            for label, value in (
                ("DOF", data.get("dof")),
                ("URDF", data.get("urdf") or None),
                ("USD", data.get("usd") or None),
                (_("robot.info.sensors"), ", ".join(map(str, sensors)) or "—"),
                (_("robot.info.tasks"), ", ".join(map(str, tasks)) or "—"),
            ):
                if value not in (None, ""):
                    output.echo(f"  {label}: {value}")

    return app
