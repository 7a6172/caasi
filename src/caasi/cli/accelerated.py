"""Wave A ecosystem groups (``plan3.md`` §12, §15, §18, §20-23).

The commands every accelerated group shares — ``status``, ``list``, ``doctor``
and the verb that starts an upstream tool — are generated from the catalog by
:func:`caasi.cli.ecosystem.build_group`. This module only adds the commands
that need group-specific knowledge, and each of them delegates: cameras come
from ``/dev``, the graph from ``ros2 node info``, maps from the YAML a Nav2 map
server wrote, timings from ``ros2 topic hz``. Nothing here implements SLAM,
perception or motion planning.
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path
from typing import Any, Optional

import typer
import yaml
from rich.table import Table

from .. import state
from ..checks import CheckResult
from ..core import catalog, nvidia, ros as ros_core, rosenv, sensors
from ..i18n import _
from ..utils import output, pydist
from . import ecosystem as eco

#: Environment variable that points at an Isaac ROS workspace.
ISAAC_ROS_WS_ENV = "ISAAC_ROS_WS"

#: Common Isaac ROS workspace locations (after the env var and the registry).
COMMON_WORKSPACES = ("~/workspaces/isaac_ros", "~/isaac_ros")

#: Image message types a camera topic can carry.
IMAGE_TYPES = ("sensor_msgs/msg/Image", "sensor_msgs/msg/CompressedImage")

#: ``ros2 topic list -t`` line: ``/topic [type]``.
TOPIC_TYPE_RE = re.compile(r"^(\S+)\s+\[([^\]]+)\]$")

#: Distribution names TensorRT is published under.
TENSORRT_DISTS = ("tensorrt", "tensorrt-cu12", "tensorrt-cu11", "tensorrt_cu12")

#: ``perception`` verb → the Isaac ROS capability it launches.
PERCEPTION_RUNS = {"detect": "detection", "segment": "segmentation"}

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
PNM_MAGICS = (b"P1", b"P2", b"P4", b"P5")


# -- discovery helpers ----------------------------------------------------


def isaac_ros_workspace() -> str | None:
    """Env ``ISAAC_ROS_WS`` → ``tools.isaacros`` registry → common paths."""
    env_value = os.environ.get(ISAAC_ROS_WS_ENV)
    if env_value:
        candidate = Path(env_value).expanduser()
        if candidate.is_dir():
            return str(candidate)
    root = catalog.tool_root(state.cfg(), "isaacros")
    if root is not None:
        return str(root)
    for pattern in COMMON_WORKSPACES:
        candidate = Path(pattern).expanduser()
        if candidate.is_dir():
            return str(candidate)
    return None


def gpu_name() -> str | None:
    if not nvidia.available():
        return None
    try:
        gpus = nvidia.query(["name"])
    except nvidia.NvidiaSmiError:
        return None
    return str(gpus[0]["name"]) if gpus else None


def image_topics() -> list[tuple[str, str]]:
    """Live topics carrying image messages (``ros2 topic list -t``)."""
    if not ros_core.find_ros2_binary():
        return []
    found: list[tuple[str, str]] = []
    for line in ros_core.ros2_lines(["topic", "list", "-t"]):
        match = TOPIC_TYPE_RE.match(line)
        if match and match.group(2) in IMAGE_TYPES:
            found.append((match.group(1), match.group(2)))
    return found


def perception_nodes() -> list[str]:
    """Running nodes that belong to a ``perception`` capability."""
    running = eco.running_capabilities("perception")
    return sorted({node for group in running.values() for node in group})


def pose_topic() -> str:
    """The pose topic from the catalog (``--topic`` overrides it)."""
    item = catalog.resolve_capability("perception", "pose", state.cfg())
    topics = item.capability.topics if item else ()
    return topics[-1] if topics else "/tf"


def image_size(path: Path) -> tuple[int, int] | None:
    """(width, height) read from PNG/PGM header bytes — no image library."""
    try:
        with path.open("rb") as handle:
            head = handle.read(1024)
    except OSError:
        return None
    if head.startswith(PNG_SIGNATURE) and head[12:16] == b"IHDR" and len(head) >= 24:
        return int.from_bytes(head[16:20], "big"), int.from_bytes(head[20:24], "big")
    if head[:2] in PNM_MAGICS:
        tokens: list[str] = []
        for line in head.splitlines()[1:]:
            tokens.extend(line.split(b"#")[0].decode("ascii", "replace").split())
            if len(tokens) >= 2:
                break
        if len(tokens) >= 2 and tokens[0].isdigit() and tokens[1].isdigit():
            return int(tokens[0]), int(tokens[1])
    return None


# -- status / doctor extras ----------------------------------------------


def isaacros_status_extra() -> dict[str, Any]:
    return {"workspace": isaac_ros_workspace()}


def motion_status_extra() -> dict[str, Any]:
    return {"gpu": gpu_name()}


def nitros_status_extra() -> dict[str, Any]:
    return {
        "cuda": nvidia.cuda_version(),
        "tensorrt": pydist.pip_version(*TENSORRT_DISTS),
    }


def nitros_doctor_extra() -> list[CheckResult]:
    """Explain NITROS and report whether the running graph mixes GPU and CPU."""
    results = [
        CheckResult(
            "accelerated",
            _("nitros.explain"),
            "skip",
            _("nitros.explain_detail"),
            _("nitros.explain_hint"),
        )
    ]
    findings = eco.graph_findings(with_qos=False)
    boundaries = findings["boundaries"]
    if not findings["nodes"]:
        return results
    if boundaries:
        results.append(
            CheckResult(
                "accelerated",
                _("nitros.graph_mixing"),
                "warn",
                _(
                    "nitros.graph_mixing_detail",
                    count=len(boundaries),
                    topic=boundaries[0]["topic"],
                ),
                _("nitros.graph_mixing_hint"),
            )
        )
    else:
        results.append(
            CheckResult(
                "accelerated",
                _("nitros.graph_mixing"),
                "ok",
                _("nitros.graph_clean", nodes=len(findings["nodes"])),
            )
        )
    return results


# -- caasi isaac-ros -----------------------------------------------------

isaacros_app = eco.build_group("isaacros", status_extra=isaacros_status_extra)


# -- caasi perception ----------------------------------------------------

perception_app = eco.build_group("perception")


@perception_app.command(
    "camera", help=_("perception.camera_help"), context_settings=eco.EXTRA_SETTINGS
)
def perception_camera(
    ctx: typer.Context,
    hz: Optional[str] = typer.Option(None, "--hz", help=_("perception.flag.hz")),
    duration: float = typer.Option(5.0, "--duration", help=_("ecosystem.flag.duration")),
    window: int = typer.Option(10, "--window", help=_("perception.flag.window")),
    json_output: bool = typer.Option(False, "--json", help=_("flag.json")),
) -> None:
    if hz:
        binary = eco.binary_or_fail()
        command = [binary, "topic", "hz", "--window", str(window), hz, *[str(a) for a in ctx.args]]
        if json_output:
            output.echo_json(eco.sample_rate(hz, window=window, duration=duration))
            return
        bounded, has_timeout = eco.with_duration(command, duration)
        if not has_timeout:
            output.echo(f"[dim]{_('ecosystem.no_timeout')}[/dim]")
        eco.exec_pass_through(bounded)
        return

    devices = sensors.list_cameras()
    topics = image_topics()
    payload = {
        "devices": [{"device": device, "name": name} for device, name in devices],
        "topics": [{"topic": topic, "type": kind} for topic, kind in topics],
    }
    if output.wants_json(json_output):
        output.echo_json(payload)
        return

    output.echo(f"[bold]{_('perception.camera_title')}[/bold]")
    table = Table(header_style="bold", **output.table_styles())
    table.add_column(_("perception.col.device"))
    table.add_column(_("perception.col.name"))
    for device, name in devices:
        table.add_row(device, name or "—")
    output.echo(table)

    if topics:
        output.echo(f"[bold]{_('perception.topics_title')}[/bold]")
        topic_table = Table(header_style="bold", **output.table_styles())
        topic_table.add_column(_("perception.col.topic"))
        topic_table.add_column(_("perception.col.type"))
        for topic, kind in topics:
            topic_table.add_row(topic, kind)
        output.echo(topic_table)
    else:
        output.echo(f"[dim]{_('perception.no_image_topics')}[/dim]")
    if not devices and not topics:
        output.echo(f"[dim]{_('perception.no_camera_hint')}[/dim]")


@perception_app.command(
    "pose", help=_("perception.pose_help"), context_settings=eco.EXTRA_SETTINGS
)
def perception_pose(
    ctx: typer.Context,
    topic: Optional[str] = typer.Option(None, "--topic", "-t", help=_("perception.flag.topic")),
    json_output: bool = typer.Option(False, "--json", help=_("flag.json")),
) -> None:
    binary = eco.binary_or_fail()
    target = topic or pose_topic()
    command = [binary, "topic", "echo", target, *[str(a) for a in ctx.args]]
    eco.exec_pass_through(rosenv.wrap(command), json_output=json_output)


def start_perception(
    verb: str,
    ctx: typer.Context,
    name: str | None,
    dry_run: bool,
    json_output: bool,
) -> None:
    """``detect`` / ``segment``: launch the resolved Isaac ROS package."""
    cap_key = PERCEPTION_RUNS[verb]
    item = catalog.resolve_capability("isaacros", cap_key, state.cfg())
    if item is None or not item.found:
        output.fail(_("perception.not_available", cap=cap_key) + " " + _("perception.list_hint"))
        return
    eco.start_capability(
        "isaacros",
        cap_key,
        [str(arg) for arg in ctx.args],
        name=name,
        kind="perception",
        dry_run=dry_run,
        json_output=json_output,
    )


@perception_app.command(
    "detect", help=_("perception.detect_help"), context_settings=eco.EXTRA_SETTINGS
)
def perception_detect(
    ctx: typer.Context,
    name: Optional[str] = typer.Option(None, "--name", help=_("ecosystem.flag.name")),
    dry_run: bool = typer.Option(False, "--dry-run", help=_("ecosystem.flag.dry_run")),
    json_output: bool = typer.Option(False, "--json", help=_("flag.json")),
) -> None:
    start_perception("detect", ctx, name, dry_run, json_output)


@perception_app.command(
    "segment", help=_("perception.segment_help"), context_settings=eco.EXTRA_SETTINGS
)
def perception_segment(
    ctx: typer.Context,
    name: Optional[str] = typer.Option(None, "--name", help=_("ecosystem.flag.name")),
    dry_run: bool = typer.Option(False, "--dry-run", help=_("ecosystem.flag.dry_run")),
    json_output: bool = typer.Option(False, "--json", help=_("flag.json")),
) -> None:
    start_perception("segment", ctx, name, dry_run, json_output)


@perception_app.command("inspect", help=_("perception.inspect_help"))
def perception_inspect(
    node: Optional[str] = typer.Argument(None, help=_("perception.arg.node")),
    qos: bool = typer.Option(True, "--qos/--no-qos", help=_("perception.flag.qos")),
    json_output: bool = typer.Option(False, "--json", help=_("flag.json")),
) -> None:
    """``ros2 node info`` (+ QoS) for the running perception nodes."""
    nodes = [node] if node else perception_nodes()
    if not nodes:
        if output.wants_json(json_output):
            output.echo_json({"nodes": []})
            return
        output.echo(f"[dim]{_('perception.no_nodes')}[/dim]")
        output.echo(f"[dim]{_('perception.no_nodes_hint')}[/dim]")
        return

    collected = [(name, eco.node_interfaces(name)) for name in nodes]
    if output.wants_json(json_output):
        output.echo_json(
            {
                "nodes": [
                    {
                        "node": name,
                        "interfaces": {
                            section: [
                                {"endpoint": endpoint, "type": kind}
                                for endpoint, kind in entries.items()
                            ]
                            for section, entries in sections.items()
                        },
                    }
                    for name, sections in collected
                ]
            }
        )
        return
    for name, sections in collected:
        eco.echo_interfaces(name, sections, qos)


# -- caasi slam ----------------------------------------------------------

slam_app = eco.build_group("slam")


def slam_checks(
    backend: str | None, hz: bool, duration: float, window: int
) -> tuple[str, list[CheckResult]]:
    """Backend installed → node alive → its topics published (→ rate sample)."""
    section = "accelerated"
    if not ros_core.find_ros2_binary():
        return "", [
            CheckResult(
                section,
                _("catalog.domain.slam"),
                "skip",
                _("doctor.robotics.no_ros2"),
                _("doctor.robotics.no_ros2_hint"),
            )
        ]

    item = eco.pick_capability("slam", backend)
    cap = item.capability
    results = [
        CheckResult(
            section,
            _(cap.label),
            "ok",
            item.value or cap.key,
            _("adapters.found_via", how=item.how),
        )
    ]
    nodes = eco.capability_nodes(cap, eco.live_nodes())
    if nodes:
        results.append(CheckResult(section, _("slam.check.nodes"), "ok", ", ".join(nodes)))
    else:
        results.append(
            CheckResult(
                section, _("slam.check.nodes"), "fail", _("slam.no_nodes"), _("slam.no_nodes_hint")
            )
        )

    listed = set(ros_core.ros2_lines(["topic", "list"]))
    for expected in cap.topics:
        if not nodes:
            results.append(
                CheckResult(
                    section,
                    _("slam.check.topic", topic=expected),
                    "skip",
                    _("slam.no_nodes"),
                )
            )
        elif expected in listed:
            results.append(
                CheckResult(section, _("slam.check.topic", topic=expected), "ok", expected)
            )
        else:
            results.append(
                CheckResult(
                    section,
                    _("slam.check.topic", topic=expected),
                    "fail",
                    _("slam.topic_missing"),
                    _("slam.topic_missing_hint", topic=expected),
                )
            )

    if hz:
        for expected in cap.topics:
            sample = eco.sample_rate(expected, window=window, duration=duration)
            results.append(
                CheckResult(
                    section,
                    _("slam.check.rate", topic=expected),
                    "ok" if sample["rate"] else "warn",
                    sample["detail"],
                )
            )
    return cap.key, results


@slam_app.command("test", help=_("slam.test_help"))
def slam_test(
    backend: Optional[str] = typer.Option(
        None, "--backend", "-b", help=_("ecosystem.flag.backend", domain="slam")
    ),
    hz: bool = typer.Option(False, "--hz", help=_("slam.flag.hz")),
    duration: float = typer.Option(5.0, "--duration", help=_("ecosystem.flag.duration")),
    window: int = typer.Option(10, "--window", help=_("perception.flag.window")),
    verbose: bool = typer.Option(False, "--verbose", help=_("ecosystem.flag.verbose")),
    json_output: bool = typer.Option(False, "--json", help=_("flag.json")),
) -> None:
    picked, results = slam_checks(backend, hz, duration, window)
    eco.render_checks({"domain": "slam", "backend": picked}, results, verbose, json_output)


@slam_app.command(
    "benchmark", help=_("slam.benchmark_help"), context_settings=eco.EXTRA_SETTINGS
)
def slam_benchmark(
    ctx: typer.Context,
    script: Optional[Path] = typer.Option(None, "--script", help=_("slam.flag.script")),
    topic: Optional[str] = typer.Option(None, "--topic", "-t", help=_("perception.flag.topic")),
    backend: Optional[str] = typer.Option(
        None, "--backend", "-b", help=_("ecosystem.flag.backend", domain="slam")
    ),
    duration: float = typer.Option(10.0, "--duration", help=_("ecosystem.flag.duration")),
    window: int = typer.Option(10, "--window", help=_("perception.flag.window")),
    name: Optional[str] = typer.Option(None, "--name", help=_("ecosystem.flag.name")),
    dry_run: bool = typer.Option(False, "--dry-run", help=_("ecosystem.flag.dry_run")),
    json_output: bool = typer.Option(False, "--json", help=_("flag.json")),
) -> None:
    extra = [str(arg) for arg in ctx.args]
    if script is not None:
        if not script.is_file():
            output.fail(_("motion.no_script", path=script))
            return
        command = script_command(script, extra)
        eco.start_command(
            command,
            name=name or script.stem,
            kind="benchmark",
            backend="script",
            dry_run=dry_run,
            json_output=json_output,
            extra={"domain": "slam", "script": str(script)},
            report=True,
        )
        return

    item = eco.pick_capability("slam", backend)
    topics = item.capability.topics
    target = topic or (topics[0] if topics else None)
    if not target:
        output.fail(_("slam.benchmark_no_topic"))
        return
    binary = eco.binary_or_fail()
    command, bounded = eco.with_duration(
        [binary, "topic", "hz", "--window", str(window), target, *extra], duration
    )
    eco.start_command(
        command,
        eco.launch_env(),
        name=name or f"slam-hz-{target.strip('/')}",
        kind="benchmark",
        dry_run=dry_run,
        json_output=json_output,
        extra={"domain": "slam", "topic": target, "duration": duration},
        note=None if bounded else _("ecosystem.no_timeout"),
        report=True,
    )


# -- caasi mapping -------------------------------------------------------

mapping_app = eco.build_group("mapping")


@mapping_app.command("inspect", help=_("mapping.inspect_help"))
def mapping_inspect(
    map_yaml: Path = typer.Argument(..., help=_("mapping.arg.map")),
    json_output: bool = typer.Option(False, "--json", help=_("flag.json")),
) -> None:
    """Read a Nav2/ROS map YAML: resolution, origin, image size, metres."""
    if not map_yaml.is_file():
        output.fail(_("mapping.no_file", path=map_yaml))
        return
    try:
        data = yaml.safe_load(map_yaml.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as exc:
        output.fail(_("mapping.bad_yaml", error=exc))
        return
    if not isinstance(data, dict):
        output.fail(_("mapping.bad_yaml", error=_("mapping.not_a_map")))
        return

    image_name = data.get("image")
    image_path = map_yaml.parent / str(image_name) if image_name else None
    exists = bool(image_path and image_path.is_file())
    size = image_size(image_path) if exists and image_path else None
    resolution = data.get("resolution")
    width, height = size or (None, None)
    payload = {
        "path": str(map_yaml),
        "image": str(image_path) if image_path else None,
        "image_exists": exists,
        "width": width,
        "height": height,
        "resolution": resolution,
        "origin": data.get("origin"),
        "occupied_thresh": data.get("occupied_thresh"),
        "free_thresh": data.get("free_thresh"),
        "mode": data.get("mode"),
        "width_metres": _metres(width, resolution),
        "height_metres": _metres(height, resolution),
    }
    if output.wants_json(json_output):
        output.echo_json(payload)
        raise typer.Exit(0 if exists else 1)

    output.echo(f"[bold]{map_yaml.name}[/bold]")
    rows = (
        ("mapping.row.image", payload["image"] or "—"),
        ("mapping.row.exists", _("ecosystem.yes") if exists else _("ecosystem.no")),
        ("mapping.row.size", f"{width} × {height}" if size else "—"),
        ("mapping.row.resolution", f"{resolution}" if resolution is not None else "—"),
        ("mapping.row.origin", str(payload["origin"]) if payload["origin"] is not None else "—"),
        (
            "mapping.row.occupied",
            f"{payload['occupied_thresh']}" if payload["occupied_thresh"] is not None else "—",
        ),
        ("mapping.row.free", f"{payload['free_thresh']}" if payload["free_thresh"] is not None else "—"),
        ("mapping.row.mode", payload["mode"] or "—"),
        (
            "mapping.row.scale",
            _(
                "mapping.scale",
                width=payload["width_metres"],
                height=payload["height_metres"],
            )
            if payload["width_metres"] is not None
            else "—",
        ),
    )
    for key, value in rows:
        output.echo(f"  {_(key):<12} {value}")
    if not exists:
        output.fail(_("mapping.image_missing", path=payload["image"] or "—"))


def _metres(pixels: int | None, resolution: Any) -> float | None:
    if pixels is None or not isinstance(resolution, (int, float)):
        return None
    return round(pixels * float(resolution), 3)


# -- caasi motion --------------------------------------------------------

motion_app = eco.build_group("motion", status_extra=motion_status_extra)


def script_command(script: Path, extra: list[str]) -> list[str]:
    """A user script through its own interpreter (``.py`` → this Python)."""
    if script.suffix == ".py":
        return [sys.executable, str(script), *extra]
    return [str(script), *extra]


def send_goal(action: str, extra: list[str], json_output: bool) -> None:
    """``ros2 action send_goal`` after checking a server is reachable."""
    binary = eco.binary_or_fail()
    available = ros_core.ros2_lines(["action", "list"])
    if not available:
        output.fail(_("motion.no_actions") + " " + _("motion.no_actions_hint"))
        return
    if action not in available:
        output.fail(_("motion.no_action", action=action, known=", ".join(available)))
        return
    command = [binary, "action", "send_goal", action, *extra]
    eco.exec_pass_through(rosenv.wrap(command), json_output=json_output)


@motion_app.command(
    "plan", help=_("motion.plan_help"), context_settings=eco.EXTRA_SETTINGS
)
def motion_plan(
    ctx: typer.Context,
    action: str = typer.Argument(..., help=_("motion.arg.action")),
    json_output: bool = typer.Option(False, "--json", help=_("flag.json")),
) -> None:
    send_goal(action, [str(arg) for arg in ctx.args], json_output)


@motion_app.command(
    "execute", help=_("motion.execute_help"), context_settings=eco.EXTRA_SETTINGS
)
def motion_execute(
    ctx: typer.Context,
    action: str = typer.Argument(..., help=_("motion.arg.action")),
    json_output: bool = typer.Option(False, "--json", help=_("flag.json")),
) -> None:
    send_goal(action, [str(arg) for arg in ctx.args], json_output)


@motion_app.command(
    "benchmark", help=_("motion.benchmark_help"), context_settings=eco.EXTRA_SETTINGS
)
def motion_benchmark(
    ctx: typer.Context,
    script: Path = typer.Argument(..., help=_("motion.arg.script")),
    name: Optional[str] = typer.Option(None, "--name", help=_("ecosystem.flag.name")),
    dry_run: bool = typer.Option(False, "--dry-run", help=_("ecosystem.flag.dry_run")),
    json_output: bool = typer.Option(False, "--json", help=_("flag.json")),
) -> None:
    if not script.is_file():
        output.fail(_("motion.no_script", path=script))
        return
    eco.start_command(
        script_command(script, [str(arg) for arg in ctx.args]),
        name=name or script.stem,
        kind="benchmark",
        backend="script",
        dry_run=dry_run,
        json_output=json_output,
        extra={"domain": "motion", "script": str(script)},
        report=True,
    )


# -- caasi nitros --------------------------------------------------------

nitros_app = eco.build_group(
    "nitros", status_extra=nitros_status_extra, doctor_extra=nitros_doctor_extra
)


# -- caasi pipeline ------------------------------------------------------

pipeline_app = typer.Typer(no_args_is_help=True)


@pipeline_app.command("inspect", help=_("pipeline.inspect_help"))
def pipeline_inspect(
    node: Optional[str] = typer.Argument(None, help=_("pipeline.arg.node")),
    qos: bool = typer.Option(True, "--qos/--no-qos", help=_("perception.flag.qos")),
    json_output: bool = typer.Option(False, "--json", help=_("flag.json")),
) -> None:
    """What the running graph says about GPU acceleration (nothing invented)."""
    nodes = [node] if node else eco.live_nodes()
    if not nodes:
        if output.wants_json(json_output):
            output.echo_json({"nodes": [], "plain": [], "boundaries": [], "qos": []})
            return
        output.echo(f"[dim]{_('pipeline.no_nodes')}[/dim]")
        output.echo(f"[dim]{_('pipeline.no_nodes_hint')}[/dim]")
        return

    findings = eco.graph_findings(nodes, with_qos=qos)
    if output.wants_json(json_output):
        output.echo_json(findings)
        return

    output.echo(
        _(
            "pipeline.summary",
            nodes=len(findings["nodes"]),
            accelerated=len(findings["accelerated"]),
            topics=findings["topics"],
        )
    )

    if findings["plain"]:
        output.echo(f"[bold]{_('pipeline.plain_title')}[/bold]")
        table = Table(header_style="bold", **output.table_styles())
        table.add_column(_("pipeline.col.topic"))
        table.add_column(_("pipeline.col.type"))
        table.add_column(_("pipeline.col.accelerated_type"))
        for entry in findings["plain"]:
            table.add_row(entry["topic"], entry["type"], entry["accelerated_type"])
        output.echo(table)

    for entry in findings["boundaries"]:
        output.echo(
            f"[yellow]![/] "
            + _(
                "pipeline.boundary",
                topic=entry["topic"],
                gpu=", ".join(entry["accelerated"]),
                cpu=", ".join(entry["plain"]),
            )
        )
    for entry in findings["qos"]:
        output.echo(
            f"[yellow]![/] "
            + _(
                "pipeline.qos",
                topic=entry["topic"],
                publisher=entry["publisher"],
                subscriber=entry["subscriber"],
                reason=entry["reason"],
            )
        )

    if findings["plain"] or findings["boundaries"]:
        output.echo(f"[dim]{_('pipeline.recommend')}[/dim]")
    else:
        output.echo(f"[dim]{_('pipeline.clean')}[/dim]")
