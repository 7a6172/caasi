"""`caasi dataset` — generate, inspect, convert and validate datasets."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import typer
from rich.table import Table

from .. import state
from ..core import dataset as dataset_core
from ..core import experiment, runs
from ..i18n import _
from ..utils import output, shell

app = typer.Typer(no_args_is_help=True)

_DOWNLOAD_BACKENDS = ("hf", "ngc", "url")
_DOWNLOAD_TOOLS = {"hf": "hf", "ngc": "ngc", "url": "curl"}


def _require_dataset(query: str) -> Path:
    path = dataset_core.find_dataset(state.cfg(), query)
    if path is None:
        output.fail(_("dataset.not_found", query=query))
        raise typer.Exit(1)  # unreachable, keeps type-checkers happy
    return path


def _run_info(record_id: str | None) -> dict | None:
    if not record_id:
        return None
    record = runs.find_run(state.cfg(), str(record_id))
    if record is None:
        return {"id": str(record_id), "status": "unknown"}
    return {"id": record.run_id, "status": runs.effective_status(record)}


@app.command("list", help=_("dataset.list_help"))
def dataset_list(
    limit: int = typer.Option(20, "--limit", "-n", help=_("dataset.flag.limit")),
    json_output: bool = typer.Option(False, "--json", help=_("flag.json")),
) -> None:
    base = dataset_core.datasets_base(state.cfg())
    datasets = dataset_core.list_datasets(base)[: max(limit, 0)]
    entries = []
    for path in datasets:
        metadata = dataset_core.read_metadata(path)
        scan = dataset_core.scan_dataset(path)
        entries.append(
            {
                "name": path.name,
                "path": str(path),
                "status": metadata.get("status", "unknown"),
                "source": metadata.get("source"),
                "files": scan["files"],
                "size": scan["size"],
            }
        )
    if output.wants_json(json_output):
        output.echo_json({"base": str(base), "datasets": entries})
        return
    if not entries:
        output.echo(f"[yellow]{_('dataset.none')}[/yellow]")
        return
    from ..utils.sysinfo import human_bytes

    table = Table(header_style="bold", **output.table_styles())
    for column in (
        _("run.col.name"),
        _("run.col.status"),
        _("dataset.col.files"),
        _("run.col.size"),
    ):
        table.add_column(column)
    for entry in entries:
        table.add_row(
            entry["name"], entry["status"], str(entry["files"]), human_bytes(entry["size"])
        )
    output.echo(table)


@app.command(
    "generate",
    help=_("dataset.generate_help"),
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
)
def dataset_generate(
    ctx: typer.Context,
    config_path: Path = typer.Argument(..., help=_("dataset.arg.config")),
    episodes: Optional[int] = typer.Option(None, "--episodes", help=_("dataset.flag.episodes")),
    workers: Optional[int] = typer.Option(None, "--workers", help=_("dataset.flag.workers")),
    record_images: bool = typer.Option(False, "--record-images", help=_("dataset.flag.record_images")),
    record_depth: bool = typer.Option(False, "--record-depth", help=_("dataset.flag.record_depth")),
    record_lidar: bool = typer.Option(False, "--record-lidar", help=_("dataset.flag.record_lidar")),
    name: Optional[str] = typer.Option(None, "--name", help=_("dataset.flag.name")),
    dry_run: bool = typer.Option(False, "--dry-run", help=_("dataset.flag.dry_run")),
) -> None:
    cfg = state.cfg()
    try:
        exp = experiment.load_experiment(config_path)
    except experiment.ExperimentError as exc:
        output.fail(str(exc))
        return

    extra: list[str] = []
    if episodes is not None:
        extra += ["--episodes", str(episodes)]
    if workers is not None:
        extra += ["--workers", str(workers)]
    if record_images:
        extra.append("--record-images")
    if record_depth:
        extra.append("--record-depth")
    if record_lidar:
        extra.append("--record-lidar")
    if exp.headless:
        extra.append("--headless")
    extra += list(ctx.args)

    try:
        command, env = experiment.build_command(exp, cfg, extra_args=extra)
    except experiment.ExperimentError as exc:
        output.fail(str(exc))
        return

    dataset_name = name or exp.name
    if dry_run:
        output.echo(f"[bold]{_('sim.run.dry_title')}[/bold]")
        output.echo(f"  command: {' '.join(command)} --dataset-dir <dir>")
        output.echo(f"  cwd:     {exp.work_dir}")
        return

    base = dataset_core.datasets_base(cfg)
    dataset_dir = dataset_core.new_dataset_dir(base, dataset_name)
    dataset_dir.mkdir(parents=True)
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
            "workers": workers,
        },
    )
    dataset_core.write_metadata(
        dataset_dir,
        {
            "name": dataset_name,
            "created": record.created,
            "experiment": str(exp.config_path),
            "backend": exp.backend,
            "episodes": episodes,
            "workers": workers,
            "record": {
                "images": record_images,
                "depth": record_depth,
                "lidar": record_lidar,
            },
            "status": "generating",
            "run_id": record.run_id,
        },
    )
    output.echo(f"[green]{_('dataset.started', path=str(dataset_dir))}[/green]")
    output.echo(f"  [dim]{_('dataset.run_hint', id=record.run_id)}[/dim]")


@app.command("inspect", help=_("dataset.inspect_help"))
def dataset_inspect(
    query: str = typer.Argument(..., help=_("dataset.arg.query")),
    json_output: bool = typer.Option(False, "--json", help=_("flag.json")),
) -> None:
    path = _require_dataset(query)
    metadata = dataset_core.read_metadata(path)
    scan = dataset_core.scan_dataset(path)
    run = _run_info(metadata.get("run_id"))

    if output.wants_json(json_output):
        output.echo_json(
            {"path": str(path), "metadata": metadata, "contents": scan, "run": run}
        )
        return

    output.echo(f"[bold]{_('dataset.title')}[/bold] [dim]{path}[/dim]")
    if not metadata:
        output.echo(f"  [yellow]{_('dataset.no_metadata')}[/yellow]")
    else:
        for key, value in metadata.items():
            output.echo(f"  [bold]{key}[/bold]: {value}")
    if run:
        output.echo(f"  [bold]{_('dataset.row.run')}[/bold]: {run['id']} ({run['status']})")
    if scan["dirs"]:
        table = Table(header_style="bold", **output.table_styles())
        table.add_column(_("dataset.col.dir"))
        table.add_column(_("dataset.col.files"), justify="right")
        for sub, count in scan["dirs"].items():
            table.add_row(sub, str(count))
        output.echo(table)


@app.command("convert", help=_("dataset.convert_help"))
def dataset_convert(
    query: str = typer.Argument(..., help=_("dataset.arg.query")),
    to: str = typer.Option("jsonl", "--to", help=_("dataset.flag.to")),
    output_path: Optional[Path] = typer.Option(None, "--output", help=_("dataset.flag.output")),
) -> None:
    path = _require_dataset(query)
    try:
        target, count = dataset_core.write_index(path, to, output_path)
    except dataset_core.DatasetError as exc:
        output.fail(str(exc))
        return
    output.echo(_("dataset.index_written", path=str(target), count=count))


@app.command("validate", help=_("dataset.validate_help"))
def dataset_validate(
    query: str = typer.Argument(..., help=_("dataset.arg.query")),
    json_output: bool = typer.Option(False, "--json", help=_("flag.json")),
) -> None:
    path = _require_dataset(query)
    issues = dataset_core.validate_dataset(path)
    if output.wants_json(json_output):
        output.echo_json({"path": str(path), "valid": not issues, "issues": issues})
        raise typer.Exit(1 if issues else 0)
    if not issues:
        output.echo(f"[green]{_('dataset.valid', path=str(path))}[/green]")
        return
    output.echo(f"[red]{_('dataset.issues', count=len(issues))}[/red]")
    for issue in issues:
        output.echo(f"  [red]•[/red] {issue}")
    raise typer.Exit(1)


def _detect_backend(ref: str) -> str | None:
    if ref.startswith("hf://"):
        return "hf"
    if ref.startswith("ngc://"):
        return "ngc"
    if ref.startswith(("http://", "https://")):
        return "url"
    return None


def _resolve_tool(backend: str) -> str | None:
    if backend == "hf":
        return shell.which("hf") or shell.which("huggingface-cli")
    if backend == "ngc":
        return shell.which("ngc")
    return shell.which("curl") or shell.which("wget")


def _download_command(
    tool: str, backend: str, source: str, dest: Path, extra: list[str]
) -> list[str]:
    if backend == "hf":
        return [tool, "download", source, *extra, "--local-dir", str(dest)]
    if backend == "ngc":
        return [tool, "registry", "dataset", "download-version", source, *extra, "--dest", str(dest)]
    filename = source.rstrip("/").rsplit("/", 1)[-1] or "download"
    target = dest / filename
    if Path(tool).name.startswith("wget"):
        return [tool, *extra, "-O", str(target), source]
    return [tool, "-L", *extra, "-o", str(target), source]


@app.command(
    "download",
    help=_("dataset.download_help"),
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
)
def dataset_download(
    ctx: typer.Context,
    ref: str = typer.Argument(..., help=_("dataset.arg.ref")),
    backend: Optional[str] = typer.Option(None, "--backend", help=_("dataset.flag.backend")),
    name: Optional[str] = typer.Option(None, "--name", help=_("dataset.flag.name")),
    dry_run: bool = typer.Option(False, "--dry-run", help=_("dataset.flag.dry_run")),
) -> None:
    detected = backend or _detect_backend(ref)
    if detected not in _DOWNLOAD_BACKENDS:
        output.fail(_("dataset.bad_ref", ref=ref))
        return
    if detected == "url":
        source = ref
    else:
        source = ref.split("://", 1)[1] if "://" in ref else ref
    if not source.strip("/"):
        output.fail(_("dataset.bad_ref", ref=ref))
        return
    tool = _resolve_tool(detected)
    if tool is None and not dry_run:
        output.fail(_("dataset.no_tool", backend=detected))
        return

    dataset_name = name or source.rstrip("/").rsplit("/", 1)[-1]
    cfg = state.cfg()
    dataset_dir = dataset_core.new_dataset_dir(dataset_core.datasets_base(cfg), dataset_name)
    command = _download_command(
        tool or _DOWNLOAD_TOOLS[detected], detected, source, dataset_dir,
        [str(a) for a in ctx.args],
    )

    if dry_run:
        output.echo(f"[bold]{_('sim.run.dry_title')}[/bold]")
        output.echo(f"  command: {' '.join(command)}")
        output.echo(f"  dest:    {dataset_dir}")
        return

    dataset_dir.mkdir(parents=True, exist_ok=True)
    record = runs.start_run(
        cfg,
        name=dataset_name,
        command=command,
        backend=detected,
        kind="dataset",
        extra={"source": ref, "dataset": str(dataset_dir)},
    )
    dataset_core.write_metadata(
        dataset_dir,
        {
            "name": dataset_name,
            "created": record.created,
            "source": ref,
            "backend": detected,
            "status": "downloading",
            "run_id": record.run_id,
        },
    )
    output.echo(f"[green]{_('dataset.downloading', path=str(dataset_dir))}[/green]")
    output.echo(f"  [dim]{_('dataset.run_hint', id=record.run_id)}[/dim]")
