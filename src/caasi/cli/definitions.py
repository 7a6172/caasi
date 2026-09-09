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

from .. import state
from ..core import catalog, dataset as dataset_core, project as projects, rosenv, runs, usd
from ..core import ros as ros_core
from ..i18n import _
from ..utils import output, shell

#: Native pass-through [X]: unknown flags go to the delegated tool.
_EXTRA_SETTINGS = {"allow_extra_args": True, "ignore_unknown_options": True}

#: Definition keys that reference an asset file, and the tool that checks them.
_ASSET_KEYS = {"urdf": "check_urdf", "usd": "usdchecker"}


def _validate_files(root: Path, data: dict, cfg) -> tuple[list[dict], list[str]]:
    """Check every asset file a definition references.

    A file must exist; when its checker (``check_urdf`` / ``usdchecker``) is
    available it must also pass. Returns (per-file entries, issue messages).
    """
    files: list[dict] = []
    issues: list[str] = []
    for key, tool in _ASSET_KEYS.items():
        raw = data.get(key)
        if not raw:
            continue
        path = Path(str(raw)).expanduser()
        if not path.is_absolute():
            path = root / path
        entry = {
            "key": key,
            "path": str(path),
            "exists": path.exists(),
            "tool": None,
            "ok": False,
            "detail": "",
        }
        if not path.exists():
            issues.append(_("def.validate.missing_file", key=key, path=str(path)))
            files.append(entry)
            continue
        if tool == "check_urdf":
            command = usd.check_urdf_command(path, cfg)
        else:
            command = usd.usdchecker_command(path, cfg)
        if command is None:
            entry["ok"] = True
            entry["detail"] = _("def.validate.no_checker", tool=tool)
            files.append(entry)
            continue
        result = shell.run_cmd(command, timeout=30.0)
        entry["tool"] = tool
        entry["ok"] = result.ok
        if not result.ok:
            text = (result.stderr or result.stdout).strip()
            entry["detail"] = text.splitlines()[0] if text else ""
            issues.append(_("def.validate.check_failed", key=key, tool=tool))
        files.append(entry)
    return files, issues


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
        table = Table(header_style="bold", **output.table_styles())
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

    if kind in ("robot", "scene"):

        @app.command(
            "import",
            help=_(f"{kind}.import_help"),
            context_settings=_EXTRA_SETTINGS,
        )
        def import_asset(
            ctx: typer.Context,
            file: Path = typer.Argument(..., help=_("def.arg.file")),
            dry_run: bool = typer.Option(False, "--dry-run", help=_("def.flag.dry_run")),
        ) -> None:
            cfg = state.cfg()
            source = file.expanduser()
            if not source.exists():
                output.fail(_("def.no_file", path=str(source)))
                return
            try:
                converter = usd.converter_for(source, cfg, extra=[str(a) for a in ctx.args])
            except usd.UsdError as exc:
                output.fail(str(exc))
                return
            if dry_run:
                output.echo(f"[bold]{_('sim.run.dry_title')}[/bold]")
                output.echo(f"  command: {' '.join(converter.command)}")
                return
            record = runs.start_run(
                cfg,
                name=source.stem,
                command=converter.command,
                backend=converter.tool,
                kind="import",
                extra={"source": str(source), "mode": converter.mode},
            )
            output.echo(
                f"[green]{_('def.import_started', name=source.name, mode=converter.mode, tool=converter.tool)}[/green]"
            )
            output.echo(f"  [dim]{_('sim.run.watch', id=record.run_id)}[/dim]")

        @app.command("validate", help=_(f"{kind}.validate_help"))
        def validate_definition(
            name: str = typer.Argument(..., help=_("def.arg.name")),
            json_output: bool = typer.Option(False, "--json", help=_("flag.json")),
        ) -> None:
            cfg = state.cfg()
            root = _require_project()
            data = _require_definition(root, name)
            path = projects.definitions_dir(root, kind) / f"{name}.yaml"
            files, issues = _validate_files(root, data, cfg)
            if output.wants_json(json_output):
                output.echo_json(
                    {
                        "name": name,
                        "path": str(path),
                        "valid": not issues,
                        "files": files,
                        "issues": issues,
                    }
                )
                raise typer.Exit(1 if issues else 0)
            if not issues:
                output.echo(f"[green]{_('def.validate.ok', name=name)}[/green]")
                for entry in files:
                    output.echo(f"  [dim]{entry['key']}: {entry['path']}[/dim]")
                return
            output.echo(f"[red]{_('def.validate.issues', name=name, count=len(issues))}[/red]")
            for issue in issues:
                output.echo(f"  [red]•[/red] {issue}")
            raise typer.Exit(1)

    if kind == "scene":

        @app.command(
            "capture",
            help=_("scene.capture_help"),
            context_settings=_EXTRA_SETTINGS,
        )
        def scene_capture(
            ctx: typer.Context,
            topics: Optional[list[str]] = typer.Argument(None, help=_("scene.arg.topics")),
            name: Optional[str] = typer.Option(None, "--name", help=_("scene.flag.name")),
            dry_run: bool = typer.Option(False, "--dry-run", help=_("def.flag.dry_run")),
        ) -> None:
            cfg = state.cfg()
            try:
                binary = ros_core.require_ros2()
            except ros_core.RosError as exc:
                output.fail(str(exc))
                return
            dest = dataset_core.new_dataset_dir(
                dataset_core.datasets_base(cfg), name or "capture"
            )
            recorded = [str(topic) for topic in (topics or [])] or ["-a"]
            command = [
                binary, "bag", "record", *recorded, "-o", str(dest),
                *[str(a) for a in ctx.args],
            ]
            env = {} if rosenv.is_sourced() else rosenv.sourced_env()
            if dry_run:
                output.echo(f"[bold]{_('sim.run.dry_title')}[/bold]")
                output.echo(f"  command: {' '.join(command)}")
                output.echo(f"  dest:    {dest}")
                return
            dest.mkdir(parents=True, exist_ok=True)
            record = runs.start_run(
                cfg,
                name=name or "capture",
                command=command,
                env=env,
                backend="ros2",
                kind="capture",
                extra={"topics": recorded, "dataset": str(dest)},
            )
            dataset_core.write_metadata(
                dest,
                {
                    "name": name or "capture",
                    "created": record.created,
                    "kind": "capture",
                    "topics": recorded,
                    "status": "capturing",
                    "run_id": record.run_id,
                },
            )
            output.echo(f"[green]{_('scene.capturing', path=str(dest))}[/green]")
            output.echo(f"  [dim]{_('sim.run.watch', id=record.run_id)}[/dim]")

        @app.command(
            "reconstruct",
            help=_("scene.reconstruct_help"),
            context_settings=_EXTRA_SETTINGS,
        )
        def scene_reconstruct(
            ctx: typer.Context,
            capture: Path = typer.Argument(..., help=_("def.arg.capture")),
            dry_run: bool = typer.Option(False, "--dry-run", help=_("def.flag.dry_run")),
        ) -> None:
            cfg = state.cfg()
            source = capture.expanduser()
            if not source.exists():
                output.fail(_("scene.no_capture", path=str(source)))
                return
            item = catalog.resolve_capability(usd.DOMAIN, "nurec", cfg)
            if item is None or not item.found:
                targets = catalog.targets(item.capability) if item else "nurec"
                output.fail(_("scene.no_nurec", targets=targets))
                return
            argv = [str(source), *[str(a) for a in ctx.args]]
            if item.how == "binary":
                command = [str(item.value), *argv]
            else:
                from ..core import adapters

                try:
                    command, _env = adapters.adapter_for(usd.DOMAIN).command(
                        cfg, "nurec", argv
                    )
                except adapters.AdapterError as exc:
                    output.fail(str(exc))
                    return
            if dry_run:
                output.echo(f"[bold]{_('sim.run.dry_title')}[/bold]")
                output.echo(f"  command: {' '.join(command)}")
                return
            record = runs.start_run(
                cfg,
                name=source.stem or "reconstruct",
                command=command,
                backend="nurec",
                kind="reconstruct",
                extra={"capture": str(source)},
            )
            output.echo(f"[green]{_('scene.reconstruct_started', path=str(source))}[/green]")
            output.echo(f"  [dim]{_('sim.run.watch', id=record.run_id)}[/dim]")

    return app
