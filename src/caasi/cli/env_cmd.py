"""`caasi env` — inspect, fingerprint, compare and show the environment.

The §12 "CPU-Z for the robotics environment": everything is collected by
delegation (core/environment) and recorded as evidence (core/fingerprint) —
never as a reproduction promise. `env lock` resolves component versions into
``caasi.lock`` (core/lock), also as evidence, not as a freeze.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

import typer
from rich.table import Table

from .. import state
from ..core import fingerprint, lock, project as projects
from ..i18n import _
from ..utils import output

app = typer.Typer(no_args_is_help=True)


def _storage_root() -> Path:
    """`<project>/.caasi/` inside a project, else `~/.caasi/` (via HOME)."""
    root = projects.find_project_root()
    return root if root is not None else Path.home()


def _render_section(title: str, data: Any) -> None:
    console = output.console()
    console.print()
    console.print(f"[bold cyan]{title}[/bold cyan]")
    if not isinstance(data, dict) or not data:
        console.print(f"  [dim]{_('env.empty')}[/dim]")
        return
    for key, value in data.items():
        if isinstance(value, (dict, list)):
            rendered = json.dumps(value, ensure_ascii=False, default=str)
        elif value is None:
            rendered = "—"
        else:
            rendered = str(value)
        console.print(f"  [bold]{key:<22}[/bold] {rendered}")


@app.command("inspect", help=_("env.inspect_help"))
def env_inspect(
    json_output: bool = typer.Option(False, "--json", help=_("flag.json")),
) -> None:
    environment = fingerprint.collect(state.cfg())
    if output.wants_json(json_output):
        output.echo_json(environment)
        return
    output.echo(f"[bold]{_('env.title')}[/bold]")
    for section, data in environment.items():
        _render_section(_(f"env.section.{section}"), data)


@app.command("fingerprint", help=_("env.fingerprint_help"))
def env_fingerprint(
    save: bool = typer.Option(False, "--save", help=_("env.flag.save")),
    json_output: bool = typer.Option(False, "--json", help=_("flag.json")),
) -> None:
    environment = fingerprint.collect(state.cfg())
    digest = fingerprint.stable_hash(environment)
    path: Optional[Path] = None
    if save:
        path = fingerprint.write(_storage_root(), environment)
    payload = {
        "hash": digest,
        "saved": save,
        "path": str(path) if path else None,
        "environment": environment,
    }
    if output.wants_json(json_output):
        output.echo_json(payload)
        return
    output.echo(f"{_('env.fingerprint.hash', hash=digest)}")
    if path is not None:
        output.echo(f"[green]{_('env.fingerprint.saved', path=str(path))}[/green]")


@app.command("lock", help=_("env.lock_help"))
def env_lock(
    json_output: bool = typer.Option(False, "--json", help=_("flag.json")),
) -> None:
    root = projects.find_project_root()
    if root is None:
        output.fail(_("env.lock.no_project"))
        raise typer.Exit(1)  # unreachable
    resolved = lock.resolve(state.cfg(), root)
    path = lock.write(root, resolved)
    if output.wants_json(json_output):
        output.echo_json({**(lock.read(root) or {}), "path": str(path)})
        return
    output.echo(f"[green]{_('env.lock.written', path=str(path))}[/green]")
    output.echo(f"  [dim]{_('env.lock.resolved', count=len(resolved))}[/dim]")


def _load_document(source: Optional[Path]) -> tuple[dict[str, Any], str]:
    """Resolve a stored fingerprint from a path (file or directory)."""
    if source is None:
        document = fingerprint.load(_storage_root())
        if document is None:
            output.fail(_("env.no_stored"))
            raise typer.Exit(1)  # unreachable, keeps type-checkers happy
        return document, _("env.compare.stored")
    path = Path(source).expanduser()
    if path.is_dir():
        # a directory is either the environment store itself or a storage root
        direct = path / fingerprint.FINGERPRINT_FILE
        candidate = direct if direct.is_file() else fingerprint.environment_dir(path) / fingerprint.FINGERPRINT_FILE
    else:
        candidate = path
    try:
        document = json.loads(candidate.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        document = None
    if not isinstance(document, dict):
        output.fail(_("env.compare.not_found", path=str(path)))
        raise typer.Exit(1)
    return document, str(path)


@app.command("compare", help=_("env.compare_help"))
def env_compare(
    left: Optional[Path] = typer.Argument(None, help=_("env.arg.left")),
    right: Optional[Path] = typer.Argument(None, help=_("env.arg.right")),
    json_output: bool = typer.Option(False, "--json", help=_("flag.json")),
) -> None:
    left_doc, left_label = _load_document(left)
    if right is not None:
        right_doc, right_label = _load_document(right)
    else:
        right_doc, right_label = fingerprint.collect(state.cfg()), _("env.compare.current")

    differences = fingerprint.compare(left_doc, right_doc)
    payload = {
        "left": {"label": left_label, "hash": fingerprint.stable_hash(left_doc)},
        "right": {"label": right_label, "hash": fingerprint.stable_hash(right_doc)},
        "differences": [diff.to_dict() for diff in differences],
        "count": len(differences),
    }
    if output.wants_json(json_output):
        output.echo_json(payload)
        return
    if not differences:
        output.echo(
            f"[green]{_('env.compare.same', left=left_label, right=right_label)}[/green]"
        )
        return
    table = Table(
        title=_("env.compare.differences", count=len(differences)),
        header_style="bold",
        **output.table_styles(),
    )
    table.add_column(_("env.col.component"))
    table.add_column(_("env.col.field"))
    table.add_column(_("env.col.left"))
    table.add_column(_("env.col.right"))
    for diff in differences:
        table.add_row(diff.component, diff.key, str(diff.left), str(diff.right))
    output.echo(table)


@app.command("show", help=_("env.show_help"))
def env_show(
    json_output: bool = typer.Option(False, "--json", help=_("flag.json")),
) -> None:
    root = _storage_root()
    document = fingerprint.load(root)
    if document is None:
        output.fail(_("env.no_stored"))
        raise typer.Exit(1)  # unreachable, keeps type-checkers happy
    location = fingerprint.environment_dir(root) / fingerprint.FINGERPRINT_FILE
    if output.wants_json(json_output):
        output.echo_json({**document, "path": str(location)})
        return
    output.echo(f"[bold]{_('env.show.title')}[/bold]")
    output.echo(f"  [bold]{_('env.show.hash'):<14}[/bold] {document.get('hash', '—')}")
    output.echo(f"  [bold]{_('env.show.collected'):<14}[/bold] {document.get('collected_at', '—')}")
    output.echo(f"  [bold]{_('env.show.location'):<14}[/bold] {location}")
    sections = sorted(fingerprint.as_environment(document))
    output.echo(f"  [bold]{_('env.show.sections'):<14}[/bold] {', '.join(sections) or '—'}")
