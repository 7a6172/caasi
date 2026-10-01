"""`caasi sim` — run and inspect Isaac Sim experiments (headless by default).

`sim run`/`sim headless` are domain doors onto the canonical launcher
(`caasi run start`): both delegate to :func:`caasi.cli.run_cmd.launch_experiment`,
so every launch is a tracked run with its provenance bundle.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import typer
from rich.table import Table

from .. import state
from ..core.check import CheckContext, CheckEngine
from ..i18n import _
from ..utils import output
from . import check_cmd, run_cmd

app = typer.Typer(no_args_is_help=True)


def _sim_launch(
    ctx: typer.Context,
    config_path: Path,
    name: Optional[str],
    dry_run: bool,
    json_output: bool,
    force_headless: bool = False,
) -> None:
    run_cmd.launch_experiment(
        config_path,
        expect_backend="sim",
        name=name,
        kind="experiment",
        extra_args=list(ctx.args),
        force_headless=force_headless,
        dry_run=dry_run,
        json_output=json_output,
    )


@app.command(
    "run",
    help=_("sim.run_help"),
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
)
def sim_run(
    ctx: typer.Context,
    config_path: Path = typer.Argument(..., help=_("sim.run.config_help")),
    name: Optional[str] = typer.Option(None, "--name", help=_("sim.run.name_help")),
    dry_run: bool = typer.Option(False, "--dry-run", help=_("sim.run.dry_run_help")),
    json_output: bool = typer.Option(False, "--json", help=_("flag.json")),
) -> None:
    _sim_launch(ctx, config_path, name, dry_run, json_output)


@app.command(
    "headless",
    help=_("sim.headless_help"),
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
)
def sim_headless(
    ctx: typer.Context,
    config_path: Path = typer.Argument(..., help=_("sim.run.config_help")),
    name: Optional[str] = typer.Option(None, "--name", help=_("sim.run.name_help")),
    dry_run: bool = typer.Option(False, "--dry-run", help=_("sim.run.dry_run_help")),
    json_output: bool = typer.Option(False, "--json", help=_("flag.json")),
) -> None:
    _sim_launch(ctx, config_path, name, dry_run, json_output, force_headless=True)


@app.command("check", help=_("sim.check_help"))
def sim_check(
    json_output: bool = typer.Option(False, "--json", help=_("flag.json")),
) -> None:
    report = CheckEngine().one("sim", CheckContext(config=state.cfg()))
    if output.wants_json(json_output):
        output.echo_json(report.to_dict())
        raise typer.Exit(check_cmd.exit_code(report.result))
    check_cmd.render_report(report)
    raise typer.Exit(check_cmd.exit_code(report.result))


_EXTENSION_DIRS = (
    "exts",
    "extscache",
    "extsInternal",
    "extsUser",
    "extsDeprecated",
    "extsPhysics",
)


def _scan_extension_toml(path: Path) -> dict:
    """Pick the two keys we care about out of an ``extension.toml`` (no TOML dep)."""
    info: dict = {"name": None, "preload": False}
    section = None
    try:
        content = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return info
    for line in content.splitlines():
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            section = stripped[1:-1].strip()
        elif "=" in stripped and not stripped.startswith("#"):
            key, _, value = stripped.partition("=")
            value = value.split("#", 1)[0].strip().strip("\"'")
            if section == "package" and key.strip() == "name" and not info["name"]:
                info["name"] = value
            elif section == "core" and key.strip() == "preload":
                info["preload"] = value.lower() == "true"
    return info


@app.command("extensions", help=_("sim.extensions_help"))
def sim_extensions(
    enabled: bool = typer.Option(False, "--enabled", help=_("sim.extensions.enabled_help")),
    user: bool = typer.Option(False, "--user", help=_("sim.extensions.user_help")),
    json_output: bool = typer.Option(False, "--json", help=_("flag.json")),
) -> None:
    resolved = state.cfg().resolve_tool("isaacsim")
    root = resolved.expanded_path if resolved else None
    if root is None or not root.is_dir():
        output.fail(_("sim.status.unresolved"))
        return
    entries = []
    for dirname in (("extsUser",) if user else _EXTENSION_DIRS):
        base = root / dirname
        if not base.is_dir():
            continue
        for toml_path in sorted(base.glob("*/config/extension.toml")):
            info = _scan_extension_toml(toml_path)
            if enabled and not info["preload"]:
                continue
            entries.append(
                {
                    "name": info["name"] or toml_path.parent.parent.name,
                    "source": dirname,
                    "enabled": info["preload"],
                }
            )
    if output.wants_json(json_output):
        output.echo_json(entries)
        return
    if not entries:
        output.echo(f"[dim]{_('sim.extensions.none')}[/dim]")
        return
    table = Table(header_style="bold", **output.table_styles())
    table.add_column(_("sim.extensions.col.name"))
    table.add_column(_("sim.extensions.col.source"))
    table.add_column(_("sim.extensions.col.enabled"))
    for entry in entries:
        table.add_row(entry["name"], entry["source"], "✓" if entry["enabled"] else "—")
    output.echo(table)
