"""`caasi project` — inspect and manage Caasi projects."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import typer
import yaml
from rich.table import Table

from ..core import components
from ..core import project as projects
from ..core.config import get_dotted, load_yaml_file, set_dotted
from ..i18n import _
from ..utils import output
from .definitions import build_app
from .init_cmd import init_command

app = typer.Typer(no_args_is_help=True)

# `project init` is canonical; root `caasi init` is a thin alias (v0.3.0 IA move).
app.command("init", help=_("init.help"))(init_command)



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


@app.command("add", help=_("project.add_help"))
def project_add(
    component: str = typer.Argument(..., help=_("project.arg.component")),
    json_output: bool = typer.Option(False, "--json", help=_("flag.json")),
) -> None:
    root = require_project()
    comp = components.get(component)
    if comp is None:
        known = ", ".join(c.cli for c in components.all())
        output.fail(_("project.add.unknown", name=component, known=known))
        raise typer.Exit(1)
    projects.add_component(root, comp.key)
    payload = {"component": comp.key, "cli": comp.cli, "dirs": list(comp.dirs)}
    if output.wants_json(json_output):
        output.echo_json(payload)
        return
    output.echo(f"[green]{_('project.add.done', name=comp.cli)}[/green]")
    for sub in comp.dirs:
        output.echo(f"  [dim]{sub}/[/dim]")


@app.command("remove", help=_("project.remove_help"))
def project_remove(
    component: str = typer.Argument(..., help=_("project.arg.component")),
    purge: bool = typer.Option(False, "--purge", help=_("project.flag.purge")),
    json_output: bool = typer.Option(False, "--json", help=_("flag.json")),
) -> None:
    root = require_project()
    comp = components.get(component)
    if comp is None:
        output.fail(_("project.remove.unknown", name=component))
        raise typer.Exit(1)
    if comp.key not in projects.registered_components(root):
        output.fail(_("project.remove.not_registered", name=comp.cli))
        raise typer.Exit(1)
    _manifest, changes = projects.remove_component(root, comp.key, purge=purge)
    payload = {
        "component": comp.key,
        "removed": changes["removed"],
        "kept": changes["kept"],
        "purged": purge,
    }
    if output.wants_json(json_output):
        output.echo_json(payload)
        return
    output.echo(f"[green]{_('project.remove.done', name=comp.cli)}[/green]")
    for sub in changes["removed"]:
        output.echo(f"  [dim]- {sub}/[/dim]")
    for sub in changes["kept"]:
        output.echo(f"  [yellow]{_('project.remove.kept', dir=sub)}[/yellow]")


@app.command("list", help=_("project.list_help"))
def project_list(
    json_output: bool = typer.Option(False, "--json", help=_("flag.json")),
) -> None:
    root = require_project()
    registered = set(projects.registered_components(root))
    rows = []
    for comp in components.all():
        present = all((root / sub).is_dir() for sub in comp.dirs) if comp.dirs else False
        rows.append(
            {
                "component": comp.cli,
                "registered": comp.key in registered,
                "dirs": list(comp.dirs),
                "present": present,
            }
        )
    if output.wants_json(json_output):
        output.echo_json(rows)
        return
    table = Table(header_style="bold", **output.table_styles())
    table.add_column(_("project.col.component"))
    table.add_column(_("project.col.registered"))
    table.add_column(_("project.col.dirs"))
    for row in rows:
        mark = "[green]✓[/green]" if row["registered"] else "[dim]•[/dim]"
        state = (
            _("project.state.present")
            if row["present"]
            else _("project.state.missing")
        )
        suffix = "" if row["registered"] else f" [dim]({state})[/dim]"
        table.add_row(row["component"], mark, ", ".join(row["dirs"]) + suffix)
    output.echo(table)


@app.command("inspect", help=_("project.inspect_help"))
def project_inspect(
    json_output: bool = typer.Option(False, "--json", help=_("flag.json")),
) -> None:
    root = require_project()
    manifest = projects.read_manifest(root)
    counts = {kind: len(projects.list_definitions(root, kind)) for kind in projects.COMPONENT_KINDS}
    payload = {
        "root": str(root),
        "schema": manifest.schema,
        "name": manifest.name,
        "version": manifest.version,
        "components": sorted(manifest.registered()),
        "requires": manifest.requires,
        "tested": manifest.tested,
        "counts": counts,
    }
    if output.wants_json(json_output):
        output.echo_json(payload)
        return
    table = Table(header_style="bold", show_header=False, **output.table_styles())
    table.add_column(style="bold")
    table.add_column()
    table.add_row(_("project.row.root"), payload["root"])
    table.add_row(_("project.row.name"), payload["name"] or "—")
    table.add_row(_("project.row.version"), payload["version"])
    table.add_row(_("project.row.schema"), str(payload["schema"]))
    table.add_row(_("project.row.components"), ", ".join(payload["components"]) or "—")
    table.add_row(_("project.row.requires"), str(len(payload["requires"])))
    output.echo(table)


@app.command("add-file", help=_("project.add_file_help"))
def project_add_file(
    domain: str = typer.Argument(..., help=_("project.arg.domain")),
    kind: str = typer.Argument(..., help=_("project.arg.kind")),
    file: Path = typer.Argument(..., help=_("project.arg.file")),
    json_output: bool = typer.Option(False, "--json", help=_("flag.json")),
) -> None:
    root = require_project()
    source = Path(file).expanduser()
    try:
        dest = projects.place_file(root, domain, kind, source)
    except projects.ProjectError as exc:
        output.fail(str(exc))
        raise typer.Exit(1)
    relative = dest.relative_to(root).as_posix()
    if output.wants_json(json_output):
        output.echo_json({"domain": domain, "kind": kind, "path": str(dest), "relative": relative})
        return
    output.echo(f"[green]{_('project.add_file.done', name=source.name, path=relative)}[/green]")


config_app = typer.Typer(no_args_is_help=True, help=_("project.config_help"))


@config_app.command("show", help=_("project.config.show_help"))
def project_config_show(
    json_output: bool = typer.Option(False, "--json", help=_("flag.json")),
) -> None:
    root = require_project()
    data = load_yaml_file(root / projects.PROJECT_FILE)
    if output.wants_json(json_output):
        output.echo_json(data)
        return
    output.echo(yaml.safe_dump(data, sort_keys=False, default_flow_style=False).rstrip())


@config_app.command("get", help=_("project.config.get_help"))
def project_config_get(key: str = typer.Argument(..., help=_("project.config.arg.key"))) -> None:
    root = require_project()
    data = load_yaml_file(root / projects.PROJECT_FILE)
    value = get_dotted(data, key)
    if value is None:
        output.fail(_("project.config.missing", key=key))
        raise typer.Exit(1)
    if isinstance(value, (dict, list)):
        output.echo(yaml.safe_dump(value, sort_keys=False, default_flow_style=False).rstrip())
    else:
        output.echo(str(value))


@config_app.command("set", help=_("project.config.set_help"))
def project_config_set(
    key: str = typer.Argument(..., help=_("project.config.arg.key")),
    value: str = typer.Argument(..., help=_("project.config.arg.value")),
) -> None:
    root = require_project()
    path = root / projects.PROJECT_FILE
    data = load_yaml_file(path)
    try:
        parsed = yaml.safe_load(value)
    except yaml.YAMLError:
        parsed = value
    if parsed is None:
        parsed = value
    set_dotted(data, key, parsed)
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    output.echo(_("project.config.done", key=key, value=parsed))


app.add_typer(config_app, name="config")


# robot/scene/task definitions live under `caasi project` (v0.3.0 IA move).
app.add_typer(build_app("robot"), name="robot", help=_("robot.help"))
app.add_typer(build_app("scene"), name="scene", help=_("scene.help"))
app.add_typer(build_app("task"), name="task", help=_("task.help"))

