"""`caasi config` — show, get, set, path, tools."""

from __future__ import annotations

import os

import typer
import yaml
from rich.table import Table

from .. import state
from ..core.config import ENV_CONFIG, global_config_path, project_config_path
from ..i18n import _
from ..utils import output

app = typer.Typer(no_args_is_help=True)


@app.command("show")
def config_show(json_output: bool = typer.Option(False, "--json", help=_("flag.json"))) -> None:
    cfg = state.cfg()
    if output.wants_json(json_output):
        output.echo_json(cfg.data)
        return
    output.echo(
        yaml.safe_dump(cfg.data, sort_keys=False, default_flow_style=False).rstrip()
    )


@app.command("get")
def config_get(key: str = typer.Argument(..., help=_("config.get.key_help"))) -> None:
    cfg = state.cfg()
    if cfg.get(key) is None:
        output.fail(_("config.get.missing", key=key))
        return
    value = cfg.get(key)
    if isinstance(value, (dict, list)):
        output.echo(yaml.safe_dump(value, sort_keys=False, default_flow_style=False).rstrip())
    else:
        output.echo(str(value))


@app.command("set")
def config_set(
    key: str = typer.Argument(..., help=_("config.set.key_help")),
    value: str = typer.Argument(..., help=_("config.set.value_help")),
) -> None:
    cfg = state.cfg()
    try:
        parsed = yaml.safe_load(value)
    except yaml.YAMLError:
        parsed = value
    if parsed is None:
        parsed = value
    cfg.set(key, parsed)
    saved = cfg.save()
    output.echo(_("config.set.done", key=key, value=parsed, file=saved))


@app.command("path")
def config_path() -> None:
    cfg = state.cfg()
    flag_path = state.get().config_path
    env_path = os.environ.get(ENV_CONFIG)

    output.echo(f"[bold]{_('config.path.title')}[/bold]")
    entries = [
        ("--config", str(flag_path) if flag_path else _("config.path.unset"), bool(flag_path)),
        (ENV_CONFIG, env_path or _("config.path.unset"), bool(env_path)),
        (_("config.path.global"), str(global_config_path()), global_config_path().is_file()),
        (_("config.path.project"), str(project_config_path()), project_config_path().is_file()),
    ]
    for label, path, active in entries:
        mark = "[green]✓[/green]" if active else "[dim]•[/dim]"
        output.echo(f"  {mark} {label}: {path}")
    output.echo()
    output.echo(f"[dim]{_('config.path.precedence')}[/dim]")
    for source in cfg.sources:
        output.echo(f"  ↳ {source}")


@app.command("tools")
def config_tools(json_output: bool = typer.Option(False, "--json", help=_("flag.json"))) -> None:
    cfg = state.cfg()
    tools = cfg.tools()
    if not tools:
        output.echo(f"[yellow]{_('config.tools.empty')}[/yellow]")
        output.echo(f"[dim]{_('config.tools.hint')}[/dim]")
        return

    payload = {}
    for name, entry in tools.items():
        if not isinstance(entry, dict):
            continue
        resolved = cfg.resolve_tool(name)
        versions = entry.get("versions") if isinstance(entry.get("versions"), dict) else {}
        payload[name] = {
            "default": entry.get("default"),
            "versions": {str(k): v for k, v in versions.items()} if versions else {},
            "resolved": (
                {"version": resolved.version, "path": resolved.path, "python": resolved.python}
                if resolved
                else None
            ),
        }

    if output.wants_json(json_output):
        output.echo_json(payload)
        return

    table = Table(title=_("config.tools.title"), header_style="bold")
    for column in (_("config.tools.col.tool"), _("config.tools.col.default"), _("config.tools.col.versions"), _("config.tools.col.path")):
        table.add_column(column)
    for name, info in payload.items():
        default = info["default"]
        versions = ", ".join(
            f"[bold]{v}[/bold]" if default is not None and str(v) == str(default) else v
            for v in info["versions"]
        ) or "—"
        path = info["resolved"]["path"] if info["resolved"] else _("config.tools.unresolved")
        table.add_row(name, str(default) if default is not None else "—", versions, str(path))
    output.echo(table)


if __name__ == "__main__":  # pragma: no cover
    app()
