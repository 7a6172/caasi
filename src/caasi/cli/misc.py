"""`caasi version` and `caasi info`."""

from __future__ import annotations

import platform
import sys

import typer

from .. import __version__, state
from ..checks.isaac import detect_isaac_lab, detect_isaac_sim
from ..core import nvidia
from ..core import ros as ros_core
from ..i18n import _
from ..utils import output, pydist


def version_command(
    json_output: bool = typer.Option(False, "--json", help=_("flag.json")),
) -> None:
    if output.wants_json(json_output):
        output.echo_json({"name": "caasi", "version": __version__})
        return
    output.echo(f"caasi {__version__}")


def _ecosystem() -> dict[str, str | None]:
    cfg = state.cfg()
    _, sim_detail, _sim_hint = detect_isaac_sim(cfg)
    _, lab_detail, _lab_hint = detect_isaac_lab(cfg)
    distro, _ = ros_core.find_distro()
    cuda = nvidia.cuda_version() if nvidia.available() else None
    return {
        "isaac_sim": sim_detail,
        "isaac_lab": lab_detail,
        "ros2": distro,
        "cuda": cuda,
        "pytorch": pydist.pip_version("torch"),
        "tensorrt": pydist.pip_version("tensorrt", "tensorrt_libs"),
    }


def info_command(
    json_output: bool = typer.Option(False, "--json", help=_("flag.json")),
) -> None:
    cfg = state.cfg()

    cli_info = {
        "name": "caasi",
        "version": __version__,
        "python": platform.python_version(),
        "executable": sys.executable,
        "platform": " ".join(platform.uname()),
    }
    config_info = {
        "language": cfg.language,
        "sources": [str(p) for p in cfg.sources],
    }
    tools_info = {}
    for name in cfg.tools():
        resolved = cfg.resolve_tool(name)
        if resolved:
            tools_info[name] = {
                "version": resolved.version,
                "path": resolved.path,
                "python": resolved.python,
            }
    ecosystem = _ecosystem()

    if output.wants_json(json_output):
        output.echo_json(
            {"cli": cli_info, "config": config_info, "tools": tools_info, "ecosystem": ecosystem}
        )
        return

    console = output.console()
    console.print(f"[bold]{_('info.title')}[/bold]")

    def section(title: str, rows: list[tuple[str, str]]) -> None:
        console.print()
        console.print(f"[bold cyan]{title}[/bold cyan]")
        for label, value in rows:
            console.print(f"  [bold]{label:<16}[/bold] {value}")

    section(
        _("info.section.cli"),
        [
            (_("info.row.version"), cli_info["version"]),
            (_("info.row.python"), f"{cli_info['python']} ({cli_info['executable']})"),
            (_("info.row.platform"), cli_info["platform"]),
        ],
    )
    section(
        _("info.section.config"),
        [
            (_("info.row.language"), config_info["language"]),
            (
                _("info.row.sources"),
                ", ".join(config_info["sources"]) if config_info["sources"] else _("info.row.none"),
            ),
        ],
    )
    section(
        _("info.section.tools"),
        [
            (name, f"{info['version'] or '?'} → {info['path'] or '?'}") for name, info in tools_info.items()
        ]
        or [("", _("info.row.none"))],
    )
    section(
        _("info.section.ecosystem"),
        [
            (_("info.row.isaac_sim"), ecosystem["isaac_sim"] or _("info.row.unknown")),
            (_("info.row.isaac_lab"), ecosystem["isaac_lab"] or _("info.row.unknown")),
            (_("info.row.ros2"), ecosystem["ros2"] or _("info.row.unknown")),
            ("CUDA", ecosystem["cuda"] or _("info.row.unknown")),
            ("PyTorch", ecosystem["pytorch"] or _("info.row.unknown")),
            ("TensorRT", ecosystem["tensorrt"] or _("info.row.unknown")),
        ],
    )
