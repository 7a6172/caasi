"""`caasi gpu` — GPU status, info, memory, test (via nvidia-smi)."""

from __future__ import annotations

import sys

import typer
from rich.table import Table

from ..core import nvidia
from ..i18n import _
from ..utils import output, shell

app = typer.Typer(no_args_is_help=True)


def _require_gpus() -> list[dict]:
    try:
        return nvidia.query(nvidia.STATUS_FIELDS)
    except nvidia.NvidiaSmiError as exc:
        output.fail(_("gpu.unavailable", error=str(exc)))
        return []  # unreachable


def _fmt(value, suffix: str = "", precision: int = 0) -> str:
    if value is None:
        return "n/a"
    if precision:
        return f"{value:.{precision}f}{suffix}"
    return f"{int(value)}{suffix}"


def _idx(value) -> str:
    try:
        return str(int(value))
    except (TypeError, ValueError):
        return str(value)


@app.command("status")
def gpu_status(json_output: bool = typer.Option(False, "--json", help=_("flag.json"))) -> None:
    gpus = _require_gpus()
    cuda = nvidia.cuda_version()
    if output.wants_json(json_output):
        output.echo_json({"cuda": cuda, "gpus": gpus})
        return

    table = Table(title=_("gpu.status_title"), header_style="bold")
    for column in ("GPU", _("gpu.col.name"), _("gpu.col.vram"), _("gpu.col.util"), _("gpu.col.temp"), _("gpu.col.power"), _("gpu.col.driver")):
        table.add_column(column)
    for gpu in gpus:
        used, total = gpu.get("memory.used"), gpu.get("memory.total")
        vram = f"{_fmt((used or 0) / 1024, precision=1)} / {_fmt((total or 0) / 1024, precision=1)} GiB"
        table.add_row(
            _idx(gpu.get("index")),
            str(gpu.get("name", "?")),
            vram,
            _fmt(gpu.get("utilization.gpu"), "%"),
            _fmt(gpu.get("temperature.gpu"), "°C"),
            _fmt(gpu.get("power.draw"), " W"),
            f"{gpu.get('driver_version', '?')} / CUDA {cuda or '?'}",
        )
    output.echo(table)


@app.command("info")
def gpu_info(json_output: bool = typer.Option(False, "--json", help=_("flag.json"))) -> None:
    try:
        gpus = nvidia.query(nvidia.INFO_FIELDS)
    except nvidia.NvidiaSmiError as exc:
        output.fail(_("gpu.unavailable", error=str(exc)))
        return
    cuda = nvidia.cuda_version()
    if output.wants_json(json_output):
        output.echo_json({"cuda": cuda, "gpus": gpus})
        return

    for gpu in gpus:
        output.echo(f"[bold]{_('gpu.info_title')} {_idx(gpu.get('index'))}[/bold]")
        rows = (
            (_("gpu.col.name"), gpu.get("name")),
            ("UUID", gpu.get("uuid")),
            (_("gpu.info.serial"), gpu.get("serial")),
            ("PCI", gpu.get("pci.bus_id")),
            (_("gpu.info.compute_cap"), gpu.get("compute_cap")),
            ("ECC", gpu.get("ecc.mode.current")),
            (_("gpu.col.driver"), gpu.get("driver_version")),
            ("CUDA", cuda),
        )
        for label, value in rows:
            output.echo(f"  {label:<14} {value if value not in (None, '') else 'n/a'}")
        output.echo()


@app.command("memory")
def gpu_memory(json_output: bool = typer.Option(False, "--json", help=_("flag.json"))) -> None:
    gpus = _require_gpus()
    apps = nvidia.compute_apps()
    if output.wants_json(json_output):
        output.echo_json({"gpus": gpus, "compute_apps": apps})
        return

    table = Table(title=_("gpu.memory_title"), header_style="bold")
    for column in ("GPU", _("gpu.col.name"), _("gpu.col.vram"), _("gpu.col.free")):
        table.add_column(column)
    for gpu in gpus:
        used, total, free = gpu.get("memory.used"), gpu.get("memory.total"), gpu.get("memory.free")
        table.add_row(
            _idx(gpu.get("index")),
            str(gpu.get("name", "?")),
            f"{_fmt((used or 0) / 1024, precision=1)} / {_fmt((total or 0) / 1024, precision=1)} GiB",
            f"{_fmt((free or 0) / 1024, precision=1)} GiB",
        )
    output.echo(table)

    if apps:
        app_table = Table(title=_("gpu.apps_title"), header_style="bold")
        for column in ("PID", _("gpu.col.process"), _("gpu.col.vram")):
            app_table.add_column(column)
        for proc in apps:
            app_table.add_row(
                str(int(proc.get("pid") or 0)),
                str(proc.get("process_name", "?")),
                _fmt((proc.get("used_memory_mb") or 0) / 1024, " GiB", precision=2),
            )
        output.echo(app_table)
    else:
        output.echo(f"[dim]{_('gpu.no_apps')}[/dim]")


_TORCH_SNIPPET = (
    "import torch\n"
    "assert torch.cuda.is_available(), 'CUDA not available'\n"
    "a = torch.randn(512, 512, device='cuda')\n"
    "_ = a @ a\n"
    "torch.cuda.synchronize()\n"
    "print('cuda-ok', torch.version_cuda if hasattr(torch, 'version_cuda') else torch.version.cuda)\n"
)


@app.command("test")
def gpu_test() -> None:
    try:
        gpus = nvidia.query(["index", "name"])
    except nvidia.NvidiaSmiError as exc:
        output.fail(_("gpu.unavailable", error=str(exc)))
        return
    output.echo(_("gpu.test_driver_ok").format(count=len(gpus)))

    import_check = shell.run_cmd([sys.executable, "-c", "import torch"], timeout=30)
    if not import_check.ok:
        output.echo(f"[yellow]{_('gpu.test_no_torch')}[/yellow]")
        raise typer.Exit(0)

    result = shell.run_cmd([sys.executable, "-c", _TORCH_SNIPPET], timeout=90)
    if result.ok and "cuda-ok" in result.stdout:
        version = result.stdout.split()[-1] if result.stdout.split() else "?"
        output.echo(f"[green]{_('gpu.test_compute_ok').format(version=version)}[/green]")
        raise typer.Exit(0)
    tail = (result.stderr or result.stdout).strip().splitlines()[-1:] or [""]
    output.fail(_("gpu.test_compute_fail").format(error=tail[0]))


if __name__ == "__main__":  # pragma: no cover
    app()
