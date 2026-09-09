"""`caasi synth` — synthetic data generation with Isaac Sim Replicator.

Caasi adds no SDG engine: ``generate`` reuses the experiment runner
(``backend: sim``) after checking the Replicator extension resolves from the
``sdg`` catalog domain, and the run writes into ``CAASI_DATASET_DIR``.
``preview`` and ``validate`` are filesystem-only summaries of the
``plan3.md`` §30 tree (``rgb/depth/segmentation/bounding_boxes/metadata``);
one rgb frame counts as one produced episode and no image is ever decoded.
"""

from __future__ import annotations

import datetime as _dt
from pathlib import Path
from typing import Any, Optional

import typer
from rich.table import Table

from .. import state
from ..core import catalog, dataset as dataset_core, experiment, runs
from ..i18n import _
from ..utils import output
from ..utils.sysinfo import human_bytes
from . import ecosystem as eco
from .dataset_cmd import _require_dataset, _run_info

app = typer.Typer(no_args_is_help=True)

#: Native pass-through [X]: unknown flags go to the delegated tool.
_EXTRA_SETTINGS = {"allow_extra_args": True, "ignore_unknown_options": True}

DOMAIN = "sdg"

#: The dataset tree from ``plan3.md`` §30.
SYNTH_DIRS = ("rgb", "depth", "segmentation", "bounding_boxes", "metadata")


def _dir_counts(path: Path) -> dict[str, int]:
    counts: dict[str, int] = {}
    for sub in SYNTH_DIRS:
        folder = path / sub
        counts[sub] = (
            sum(1 for child in folder.rglob("*") if child.is_file()) if folder.is_dir() else 0
        )
    return counts


def _elapsed(metadata: dict[str, Any]) -> float | None:
    """Seconds since the dataset was created (None when unparseable)."""
    created = metadata.get("created")
    if not created:
        return None
    try:
        start = _dt.datetime.fromisoformat(str(created))
    except ValueError:
        return None
    return round((_dt.datetime.now().astimezone() - start).total_seconds(), 1)


@app.command("status", help=_("synth.status_help"))
def synth_status(
    json_output: bool = typer.Option(False, "--json", help=_("flag.json")),
) -> None:
    eco.echo_status(DOMAIN, json_output)


@app.command(
    "generate",
    help=_("synth.generate_help"),
    context_settings=_EXTRA_SETTINGS,
)
def synth_generate(
    ctx: typer.Context,
    config_path: Path = typer.Argument(..., help=_("synth.arg.config")),
    episodes: Optional[int] = typer.Option(None, "--episodes", help=_("dataset.flag.episodes")),
    output_dir: Optional[Path] = typer.Option(None, "--output", help=_("synth.flag.output")),
    dry_run: bool = typer.Option(False, "--dry-run", help=_("synth.flag.dry_run")),
) -> None:
    cfg = state.cfg()
    item = catalog.resolve_capability(DOMAIN, "replicator", cfg)
    if item is None or not item.found:
        targets = catalog.targets(item.capability) if item else "omni.replicator.core"
        output.fail(_("synth.no_replicator", targets=targets))
        return

    try:
        exp = experiment.load_experiment(config_path)
    except experiment.ExperimentError as exc:
        output.fail(str(exc))
        return

    extra: list[str] = []
    if episodes is not None:
        extra += ["--episodes", str(episodes)]
    if exp.headless:
        extra.append("--headless")
    extra += [str(a) for a in ctx.args]

    try:
        command, env = experiment.build_command(exp, cfg, extra_args=extra)
    except experiment.ExperimentError as exc:
        output.fail(str(exc))
        return

    if dry_run:
        output.echo(f"[bold]{_('sim.run.dry_title')}[/bold]")
        output.echo(f"  command: {' '.join(command)} --dataset-dir <dir>")
        output.echo(f"  cwd:     {exp.work_dir}")
        return

    if output_dir is not None:
        dataset_dir = output_dir.expanduser()
        dataset_name = dataset_dir.name
    else:
        dataset_name = exp.name
        dataset_dir = dataset_core.new_dataset_dir(dataset_core.datasets_base(cfg), dataset_name)
    dataset_dir.mkdir(parents=True, exist_ok=True)
    env["CAASI_DATASET_DIR"] = str(dataset_dir)
    command = [*command, "--dataset-dir", str(dataset_dir)]

    record = runs.start_run(
        cfg,
        name=dataset_name,
        command=command,
        cwd=exp.work_dir,
        env=env,
        backend=exp.backend,
        kind="dataset",
        extra={
            "experiment": str(exp.config_path),
            "dataset": str(dataset_dir),
            "episodes": episodes,
            "generator": "replicator",
        },
    )
    dataset_core.write_metadata(
        dataset_dir,
        {
            "name": dataset_name,
            "created": record.created,
            "generator": "replicator",
            "replicator": item.value,
            "experiment": str(exp.config_path),
            "backend": exp.backend,
            "episodes": episodes,
            "status": "generating",
            "run_id": record.run_id,
        },
    )
    output.echo(f"[green]{_('synth.started', path=str(dataset_dir))}[/green]")
    output.echo(f"  [dim]{_('sim.run.watch', id=record.run_id)}[/dim]")


@app.command("preview", help=_("synth.preview_help"))
def synth_preview(
    query: str = typer.Argument(..., help=_("dataset.arg.query")),
    json_output: bool = typer.Option(False, "--json", help=_("flag.json")),
) -> None:
    path = _require_dataset(query)
    metadata = dataset_core.read_metadata(path)
    counts = _dir_counts(path)
    scan = dataset_core.scan_dataset(path)
    run = _run_info(metadata.get("run_id"))
    payload = {
        "path": str(path),
        "name": metadata.get("name") or path.name,
        "generator": metadata.get("generator"),
        "episodes_declared": metadata.get("episodes"),
        "episodes_produced": counts["rgb"],
        "counts": counts,
        "files": scan["files"],
        "bytes": scan["size"],
        "elapsed": _elapsed(metadata),
        "run": run,
    }
    if output.wants_json(json_output):
        output.echo_json(payload)
        return

    output.echo(f"[bold]{payload['name']}[/bold] [dim]{path}[/dim]")
    declared = payload["episodes_declared"]
    output.echo(f"  {_('synth.row.generator')}: {payload['generator'] or '—'}")
    output.echo(
        f"  {_('synth.row.episodes')}: "
        + _("synth.episodes_value", produced=counts["rgb"], declared=declared if declared is not None else "—")
    )
    output.echo(f"  {_('synth.row.bytes')}: {human_bytes(scan['size'])}")
    if payload["elapsed"] is not None:
        output.echo(f"  {_('synth.row.elapsed')}: {payload['elapsed']}s")
    if run:
        output.echo(f"  {_('dataset.row.run')}: {run['id']} ({run['status']})")

    table = Table(header_style="bold", **output.table_styles())
    table.add_column(_("synth.col.dir"))
    table.add_column(_("synth.col.files"), justify="right")
    for sub in SYNTH_DIRS:
        table.add_row(sub, str(counts[sub]))
    output.echo(table)


@app.command("validate", help=_("synth.validate_help"))
def synth_validate(
    query: str = typer.Argument(..., help=_("dataset.arg.query")),
    json_output: bool = typer.Option(False, "--json", help=_("flag.json")),
) -> None:
    path = _require_dataset(query)
    issues = dataset_core.validate_dataset(path)
    metadata = dataset_core.read_metadata(path)
    counts = _dir_counts(path)
    declared = metadata.get("episodes")
    if isinstance(declared, int) and (path / "rgb").is_dir() and counts["rgb"] != declared:
        issues.append(_("synth.validate.episodes", declared=declared, produced=counts["rgb"]))
    for sub in ("depth", "segmentation", "bounding_boxes"):
        if (path / sub).is_dir() and counts[sub] != counts["rgb"]:
            issues.append(_("synth.validate.parity", sub=sub, count=counts[sub], rgb=counts["rgb"]))

    if output.wants_json(json_output):
        output.echo_json(
            {"path": str(path), "valid": not issues, "counts": counts, "issues": issues}
        )
        raise typer.Exit(1 if issues else 0)
    if not issues:
        output.echo(f"[green]{_('synth.valid', path=str(path))}[/green]")
        return
    output.echo(f"[red]{_('synth.issues', count=len(issues))}[/red]")
    for issue in issues:
        output.echo(f"  [red]•[/red] {issue}")
    raise typer.Exit(1)
