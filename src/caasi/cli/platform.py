"""Tier-4 ecosystem groups: physics, warp, groot, cosmos (``plan3.md`` §26-29, §34).

Assembled from the catalog + adapter helpers in :mod:`caasi.cli.ecosystem`;
every command resolves an upstream tool and delegates — nothing here
implements physics, GPU compute or foundation models. Where a tool is
missing the command says so and names the config key that would point at it.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import typer
from rich.table import Table

from .. import state
from ..core import experiment, physics, platform, runs
from ..i18n import _
from ..utils import output, shell
from . import ecosystem as eco

physics_app = typer.Typer(no_args_is_help=True)
warp_app = typer.Typer(no_args_is_help=True)
groot_app = typer.Typer(no_args_is_help=True)
cosmos_app = typer.Typer(no_args_is_help=True)

#: Warp device probe — always a subprocess, never imported in-process.
WARP_TEST_SNIPPET = "import warp; warp.init(); print(warp.get_devices())"

#: Bound for the Warp device probe (init can compile kernels on first run).
WARP_TEST_TIMEOUT = 120.0


# -- caasi physics ----------------------------------------------------------


@physics_app.command(
    "status", help=_("ecosystem.status_help", domain=_("catalog.domain.physics"))
)
def physics_status(
    json_output: bool = typer.Option(False, "--json", help=_("flag.json")),
) -> None:
    eco.echo_status("physics", json_output, {"engine": physics.default_engine(state.cfg())})


@physics_app.command("list", help=_("physics.list_help"))
def physics_list(
    json_output: bool = typer.Option(False, "--json", help=_("flag.json")),
) -> None:
    """Engines from the catalog: detected/absent and how they were found."""
    cfg = state.cfg()
    items = physics.engines(cfg)
    default = physics.default_engine(cfg)
    payload = {
        "domain": "physics",
        "default": default,
        "engines": [
            {
                "engine": item.capability.key,
                "installed": item.found,
                "how": item.how or None,
                "value": item.value or None,
                "launcher": physics.launcher_for(item, cfg),
            }
            for item in items
        ],
    }
    if output.wants_json(json_output):
        output.echo_json(payload)
        return

    table = Table(header_style="bold", **output.table_styles())
    table.add_column(_("physics.col.engine"))
    table.add_column(_("ecosystem.col.state"))
    table.add_column(_("physics.col.found_via"))
    table.add_column(_("ecosystem.col.detail"))
    for item in items:
        symbol, style = output.status_symbol("ok" if item.found else "skip")
        table.add_row(
            item.capability.key,
            f"[{style}]{symbol}[/]",
            item.how or "—",
            item.value or _("ecosystem.not_installed"),
        )
    output.echo(table)
    output.echo(f"[dim]{_('physics.default_note', engine=default)}[/dim]")


def _physics_start(
    config_path: Path,
    engine: str | None,
    ctx: typer.Context,
    *,
    name: str | None,
    kind: str,
    dry_run: bool,
    json_output: bool,
    report: bool,
) -> None:
    """`run`/`benchmark`: an experiment YAML through the chosen engine."""
    cfg = state.cfg()
    try:
        exp = experiment.load_experiment(config_path)
    except experiment.ExperimentError as exc:
        output.fail(str(exc))
        return
    try:
        item = physics.pick_engine(cfg, engine)
    except physics.PhysicsError as exc:
        output.fail(str(exc))
        return
    extra_args = (["--headless"] if exp.headless else []) + [str(a) for a in ctx.args]
    try:
        command, env = experiment.build_command(exp, cfg, extra_args=extra_args)
    except experiment.ExperimentError as exc:
        output.fail(str(exc))
        return
    command, env = physics.apply_engine(item, command, env, cfg)

    if dry_run:
        output.echo(f"[bold]{_('sim.run.dry_title')}[/bold]")
        output.echo(f"  command: {' '.join(str(part) for part in command)}")
        output.echo(f"  cwd:     {exp.work_dir}")
        output.echo(f"  engine:  {item.capability.key} ({physics.ENGINE_ENV})")
        return

    record = runs.start_run(
        cfg,
        name=name or exp.name,
        command=command,
        cwd=exp.work_dir,
        env=env,
        backend=exp.backend,
        kind=kind,
        extra={"experiment": str(exp.config_path), "engine": item.capability.key},
    )
    eco.echo_started(record, json_output)
    if report and not output.wants_json(json_output):
        output.echo(f"  [dim]{_('benchmark.report_hint', id=record.run_id)}[/dim]")


@physics_app.command(
    "run", help=_("physics.run_help"), context_settings=eco.EXTRA_SETTINGS
)
def physics_run(
    ctx: typer.Context,
    config_path: Path = typer.Argument(..., help=_("physics.arg.config")),
    engine: Optional[str] = typer.Option(None, "--engine", help=_("physics.flag.engine")),
    name: Optional[str] = typer.Option(None, "--name", help=_("ecosystem.flag.name")),
    dry_run: bool = typer.Option(False, "--dry-run", help=_("ecosystem.flag.dry_run")),
    json_output: bool = typer.Option(False, "--json", help=_("flag.json")),
) -> None:
    _physics_start(
        config_path, engine, ctx,
        name=name, kind="run", dry_run=dry_run, json_output=json_output, report=False,
    )


@physics_app.command(
    "benchmark", help=_("physics.benchmark_help"), context_settings=eco.EXTRA_SETTINGS
)
def physics_benchmark(
    ctx: typer.Context,
    config_path: Path = typer.Argument(..., help=_("physics.arg.config")),
    engine: Optional[str] = typer.Option(None, "--engine", help=_("physics.flag.engine")),
    name: Optional[str] = typer.Option(None, "--name", help=_("ecosystem.flag.name")),
    dry_run: bool = typer.Option(False, "--dry-run", help=_("ecosystem.flag.dry_run")),
    json_output: bool = typer.Option(False, "--json", help=_("flag.json")),
) -> None:
    _physics_start(
        config_path, engine, ctx,
        name=name, kind="benchmark", dry_run=dry_run, json_output=json_output, report=True,
    )


# -- caasi warp --------------------------------------------------------------


@warp_app.command("status", help=_("ecosystem.status_help", domain=_("catalog.domain.warp")))
def warp_status(
    json_output: bool = typer.Option(False, "--json", help=_("flag.json")),
) -> None:
    eco.echo_status("warp", json_output, {"launcher": physics.python_for(state.cfg())})


@warp_app.command("test", help=_("warp.test_help"))
def warp_test(
    json_output: bool = typer.Option(False, "--json", help=_("flag.json")),
) -> None:
    """Init Warp in a subprocess and report its devices — never in-process."""
    eco.pick_capability("warp", None)  # honest failure when Warp is absent
    python = physics.python_for(state.cfg())
    result = shell.run_cmd([python, "-c", WARP_TEST_SNIPPET], timeout=WARP_TEST_TIMEOUT)
    devices = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    if output.wants_json(json_output):
        output.echo_json(
            {
                "domain": "warp",
                "python": python,
                "returncode": result.returncode,
                "devices": devices,
                "stdout": result.stdout,
                "stderr": result.stderr,
            }
        )
        raise typer.Exit(0 if result.returncode == 0 else 1)
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip().splitlines()
        output.fail(_("warp.test.failed", detail=detail[-1] if detail else ""))
    output.echo(f"[green]{_('warp.test.ok')}[/green]")
    for line in devices:
        output.echo(f"  {line}")


@warp_app.command(
    "benchmark", help=_("warp.benchmark_help"), context_settings=eco.EXTRA_SETTINGS
)
def warp_benchmark(
    ctx: typer.Context,
    name: Optional[str] = typer.Option(None, "--name", help=_("ecosystem.flag.name")),
    dry_run: bool = typer.Option(False, "--dry-run", help=_("ecosystem.flag.dry_run")),
    json_output: bool = typer.Option(False, "--json", help=_("flag.json")),
) -> None:
    """Pass-through: run whatever you give it with the resolved Warp interpreter."""
    extra = [str(a) for a in ctx.args]
    if not extra:
        output.fail(_("warp.benchmark.no_args"))
        return
    command = [physics.python_for(state.cfg()), *extra]
    eco.start_command(
        command,
        None,
        name=name or "warp",
        kind="benchmark",
        backend="python",
        dry_run=dry_run,
        json_output=json_output,
        extra={"domain": "warp"},
        report=True,
    )


# -- caasi groot -------------------------------------------------------------


@groot_app.command("status", help=_("ecosystem.status_help", domain=_("catalog.domain.groot")))
def groot_status(
    json_output: bool = typer.Option(False, "--json", help=_("flag.json")),
) -> None:
    eco.echo_status("groot", json_output)


@groot_app.command("setup", help=_("groot.setup_help"))
def groot_setup(
    execute: bool = typer.Option(False, "--execute", help=_("groot.flag.execute")),
    name: Optional[str] = typer.Option(None, "--name", help=_("ecosystem.flag.name")),
    dry_run: bool = typer.Option(False, "--dry-run", help=_("ecosystem.flag.dry_run")),
    json_output: bool = typer.Option(False, "--json", help=_("flag.json")),
) -> None:
    """Print the repo's own install steps; execute them only with --execute."""
    cfg = state.cfg()
    try:
        command, root = platform.groot_setup(cfg)
    except platform.PlatformError as exc:
        output.fail(str(exc))
        return
    if not execute or dry_run:
        if output.wants_json(json_output):
            output.echo_json(
                {
                    "domain": "groot",
                    "executed": False,
                    "command": command,
                    "cwd": str(root),
                }
            )
            return
        output.echo(f"[bold]{_('groot.setup.title', repo=str(root))}[/bold]")
        output.echo(f"  command: {' '.join(command)}")
        output.echo(f"  cwd:     {root}")
        output.echo(f"  [dim]{_('groot.setup.hint')}[/dim]")
        return
    record = runs.start_run(
        cfg,
        name=name or "groot-setup",
        command=command,
        cwd=root,
        backend="python",
        kind="setup",
        extra={"domain": "groot", "repo": str(root)},
    )
    eco.echo_started(record, json_output)


@groot_app.command("run", help=_("groot.run_help"), context_settings=eco.EXTRA_SETTINGS)
def groot_run(
    ctx: typer.Context,
    backend: Optional[str] = typer.Option(
        None, "--backend", "-b", help=_("ecosystem.flag.backend", domain="groot")
    ),
    name: Optional[str] = typer.Option(None, "--name", help=_("ecosystem.flag.name")),
    dry_run: bool = typer.Option(False, "--dry-run", help=_("ecosystem.flag.dry_run")),
    json_output: bool = typer.Option(False, "--json", help=_("flag.json")),
) -> None:
    cfg = state.cfg()
    key = backend or platform.groot_default(cfg)
    try:
        command, root = platform.groot_command(cfg, key, [str(a) for a in ctx.args])
    except platform.PlatformError as exc:
        output.fail(str(exc))
        return
    eco.start_command(
        command,
        None,
        name=name or key,
        kind="groot",
        backend="groot",
        cwd=root,
        dry_run=dry_run,
        json_output=json_output,
        extra={"domain": "groot", "capability": key},
    )


def _groot_script_start(
    cap_key: str,
    config_path: Path,
    ctx: typer.Context,
    *,
    kind: str,
    name: str | None,
    dry_run: bool,
    json_output: bool,
) -> None:
    """`train`/`evaluate`: the repo's own script through its own interpreter."""
    cfg = state.cfg()
    if not config_path.exists():
        output.fail(_("groot.config_missing", path=str(config_path)))
        return
    try:
        command, root = platform.groot_train_command(
            cfg, cap_key, config_path, [str(a) for a in ctx.args]
        )
    except platform.PlatformError as exc:
        output.fail(str(exc))
        return
    eco.start_command(
        command,
        None,
        name=name or config_path.stem,
        kind=kind,
        backend="groot",
        cwd=root,
        dry_run=dry_run,
        json_output=json_output,
        extra={"domain": "groot", "capability": cap_key, "config": str(config_path)},
    )


@groot_app.command(
    "train", help=_("groot.train_help"), context_settings=eco.EXTRA_SETTINGS
)
def groot_train(
    ctx: typer.Context,
    config_path: Path = typer.Argument(..., help=_("groot.arg.config")),
    name: Optional[str] = typer.Option(None, "--name", help=_("ecosystem.flag.name")),
    dry_run: bool = typer.Option(False, "--dry-run", help=_("ecosystem.flag.dry_run")),
    json_output: bool = typer.Option(False, "--json", help=_("flag.json")),
) -> None:
    _groot_script_start(
        "train", config_path, ctx,
        kind="train", name=name, dry_run=dry_run, json_output=json_output,
    )


@groot_app.command(
    "evaluate", help=_("groot.evaluate_help"), context_settings=eco.EXTRA_SETTINGS
)
def groot_evaluate(
    ctx: typer.Context,
    config_path: Path = typer.Argument(..., help=_("groot.arg.config")),
    name: Optional[str] = typer.Option(None, "--name", help=_("ecosystem.flag.name")),
    dry_run: bool = typer.Option(False, "--dry-run", help=_("ecosystem.flag.dry_run")),
    json_output: bool = typer.Option(False, "--json", help=_("flag.json")),
) -> None:
    _groot_script_start(
        "evaluate", config_path, ctx,
        kind="evaluate", name=name, dry_run=dry_run, json_output=json_output,
    )


# -- caasi cosmos ------------------------------------------------------------


@cosmos_app.command(
    "status", help=_("ecosystem.status_help", domain=_("catalog.domain.cosmos"))
)
def cosmos_status(
    json_output: bool = typer.Option(False, "--json", help=_("flag.json")),
) -> None:
    eco.echo_status("cosmos", json_output)


def _cosmos_start(
    ctx: typer.Context,
    *,
    verb: str,
    kind: str,
    run_name: str,
    name: str | None,
    dry_run: bool,
    json_output: bool,
) -> None:
    extra = [str(a) for a in ctx.args]
    if not extra:
        output.fail(_("cosmos.no_args", command=f"caasi cosmos {verb}"))
        return
    try:
        command, backend = platform.cosmos_command(state.cfg(), extra)
    except platform.PlatformError as exc:
        output.fail(str(exc))
        return
    eco.start_command(
        command,
        None,
        name=name or run_name,
        kind=kind,
        backend=backend,
        dry_run=dry_run,
        json_output=json_output,
        extra={"domain": "cosmos"},
    )


@cosmos_app.command(
    "run", help=_("cosmos.run_help"), context_settings=eco.EXTRA_SETTINGS
)
def cosmos_run(
    ctx: typer.Context,
    name: Optional[str] = typer.Option(None, "--name", help=_("ecosystem.flag.name")),
    dry_run: bool = typer.Option(False, "--dry-run", help=_("ecosystem.flag.dry_run")),
    json_output: bool = typer.Option(False, "--json", help=_("flag.json")),
) -> None:
    _cosmos_start(
        ctx, verb="run", kind="cosmos", run_name="cosmos",
        name=name, dry_run=dry_run, json_output=json_output,
    )


@cosmos_app.command(
    "dataset", help=_("cosmos.dataset_help"), context_settings=eco.EXTRA_SETTINGS
)
def cosmos_dataset(
    ctx: typer.Context,
    name: Optional[str] = typer.Option(None, "--name", help=_("ecosystem.flag.name")),
    dry_run: bool = typer.Option(False, "--dry-run", help=_("ecosystem.flag.dry_run")),
    json_output: bool = typer.Option(False, "--json", help=_("flag.json")),
) -> None:
    _cosmos_start(
        ctx, verb="dataset", kind="dataset", run_name="cosmos-dataset",
        name=name, dry_run=dry_run, json_output=json_output,
    )
