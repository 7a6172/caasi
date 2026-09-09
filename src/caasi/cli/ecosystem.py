"""Catalog-driven ecosystem groups (``plan3.md`` §12-23).

:func:`build_group` generates the half of every accelerated group that is the
same for all of them — ``status``, ``list``, ``doctor`` and the verb that starts
an upstream tool as a tracked run — straight from :mod:`caasi.core.catalog` and
:mod:`caasi.core.adapters`. The group-specific commands live in
``cli/accelerated.py`` (Wave A) and ``cli/platform.py`` (Wave D).

Caasi only resolves and starts tools that already exist; it never implements
their behaviour. An upstream rename is a catalog edit, not a code change.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Optional

import typer
from rich.table import Table

from .. import state
from ..checks import CheckResult, run_checks
from ..core import adapters, catalog, ros as ros_core, rosenv, runs
from ..i18n import _
from ..utils import output, shell

EXTRA_SETTINGS = {"allow_extra_args": True, "ignore_unknown_options": True}

#: Verbs that start an upstream tool as a tracked run, in preference order.
RUN_VERBS = ("launch", "run", "serve")

#: Doctor sections per domain; defaults to the adapter's own section.
DOCTOR_SECTIONS = {
    "isaacros": ("ros", "accelerated", "nvidia", "graphics"),
    "nitros": ("accelerated", "nvidia", "graphics"),
}

#: CLI group name for the catalog domains whose name differs.
GROUP_NAMES = {"isaacros": "isaac-ros"}

#: Row labels for values a domain adds to its status payload.
ROW_LABELS = {
    "workspace": "ecosystem.row.workspace",
    "launcher": "ecosystem.row.launcher",
    "engine": "ecosystem.row.engine",
    "root": "ecosystem.row.root",
    "ros_distro": "ecosystem.row.distro",
    "ros_sourced": "ecosystem.row.sourced",
    "gpu": "ecosystem.row.gpu",
    "cuda": "ecosystem.row.cuda",
    "tensorrt": "ecosystem.row.tensorrt",
}

ISAAC_ROS_PREFIX = "isaac_ros_"

#: Plain message types that have an accelerated (NITROS) counterpart.
NITROS_TYPES = {
    "sensor_msgs/msg/Image": "isaac_ros_nitros_interfaces/msg/NitrosImage",
    "sensor_msgs/msg/CompressedImage": "isaac_ros_nitros_interfaces/msg/NitrosCompressedImage",
    "sensor_msgs/msg/CameraInfo": "isaac_ros_nitros_interfaces/msg/NitrosCameraInfo",
    "sensor_msgs/msg/Imu": "isaac_ros_nitros_interfaces/msg/NitrosImu",
    "sensor_msgs/msg/PointCloud2": "isaac_ros_nitros_interfaces/msg/NitrosPointCloud2",
    "sensor_msgs/msg/LaserScan": "isaac_ros_nitros_interfaces/msg/NitrosLaserScan",
    "nav_msgs/msg/Odometry": "isaac_ros_nitros_interfaces/msg/NitrosOdometry",
    "nav_msgs/msg/OccupancyGrid": "isaac_ros_nitros_interfaces/msg/NitrosOccupancyGrid",
    "stereo_msgs/msg/DisparityImage": "isaac_ros_nitros_interfaces/msg/NitrosDisparityImage",
}

#: Node-name tokens that mark a node as GPU-accelerated.
ACCELERATED_TOKENS = ("isaac_ros_", "nitros")

#: ``ros2 node info`` sections that describe graph edges.
NODE_SECTIONS = (
    "Subscribers",
    "Publishers",
    "Service Servers",
    "Service Clients",
    "Action Servers",
    "Action Clients",
)

#: i18n label per ``ros2 node info`` section.
SECTION_LABELS = {
    "Subscribers": "ecosystem.section.subscribers",
    "Publishers": "ecosystem.section.publishers",
    "Service Servers": "ecosystem.section.service_servers",
    "Service Clients": "ecosystem.section.service_clients",
    "Action Servers": "ecosystem.section.action_servers",
    "Action Clients": "ecosystem.section.action_clients",
}


# -- discovery helpers ----------------------------------------------------


def group_name(domain_key: str) -> str:
    return GROUP_NAMES.get(domain_key, domain_key)


def binary_or_fail() -> str:
    """The ros2 CLI, or an honest failure."""
    binary = ros_core.find_ros2_binary()
    if not binary:
        output.fail(_("native.no_ros2"))
        raise typer.Exit(1)  # unreachable, keeps type-checkers happy
    return binary


def adapter(domain_key: str) -> adapters.Adapter:
    return adapters.adapter_for(domain_key)


def domain_or_fail(domain_key: str) -> catalog.Domain:
    spec = catalog.domain(domain_key, state.cfg())
    if spec is None:
        output.fail(_("adapters.unknown_domain", domain=domain_key))
        raise typer.Exit(1)  # unreachable
    return spec


def live_nodes() -> list[str]:
    """``ros2 node list`` (empty when the CLI is unavailable)."""
    if not ros_core.find_ros2_binary():
        return []
    return ros_core.ros2_lines(["node", "list"])


def capability_nodes(cap: catalog.Capability, nodes: list[str]) -> list[str]:
    """Live nodes belonging to a capability, derived from its catalog targets."""
    keys = set()
    for name in (*cap.packages, *(cap.launch[:1] if cap.launch else ())):
        keys.add(name)
        if name.startswith(ISAAC_ROS_PREFIX):
            keys.add(name[len(ISAAC_ROS_PREFIX) :])
    return [node for node in nodes if any(key and key in node for key in keys)]


def running_capabilities(domain_key: str, nodes: list[str] | None = None) -> dict[str, list[str]]:
    """capability key → the live nodes that belong to it."""
    listed = live_nodes() if nodes is None else nodes
    if not listed:
        return {}
    found: dict[str, list[str]] = {}
    for item in catalog.resolve_domain(domain_key, state.cfg()):
        matched = capability_nodes(item.capability, listed)
        if matched:
            found[item.capability.key] = matched
    return found


def launch_env() -> dict[str, str]:
    """Environment for a raw ``ros2`` command: empty when already sourced."""
    return {} if rosenv.is_sourced() else rosenv.sourced_env()


def with_duration(command: list[str], duration: float | None) -> tuple[list[str], bool]:
    """Bound a streaming command with coreutils ``timeout`` when available."""
    if not duration:
        return command, False
    binary = shell.which("timeout")
    if not binary:
        return command, False
    seconds = f"{duration:g}"
    return [binary, seconds, *command], True


def pick_capability(domain_key: str, requested: str | None = None) -> catalog.Resolved:
    """The capability to run: ``--backend``, ``catalog.<domain>.default``, first installed."""
    cfg = state.cfg()
    spec = domain_or_fail(domain_key)

    if requested is not None:
        item = catalog.resolve_capability(domain_key, requested, cfg)
        if item is None:
            known = ", ".join(cap.key for cap in spec.capabilities)
            output.fail(
                _("ecosystem.unknown_backend", domain=group_name(domain_key), cap=requested, known=known)
            )
            raise typer.Exit(1)  # unreachable
        if not item.found:
            output.fail(
                _("adapters.missing", domain=group_name(domain_key), cap=requested,
                  targets=catalog.targets(item.capability))
                + " "
                + _("adapters.override_hint", domain=domain_key, cap=requested,
                    field=catalog.override_field(item.capability))
            )
            raise typer.Exit(1)  # unreachable
        return item

    default = catalog.domain_setting(domain_key, "default", cfg)
    if default:
        item = catalog.resolve_capability(domain_key, str(default), cfg)
        if item is not None and item.found:
            return item
    for item in catalog.resolve_domain(domain_key, cfg):
        if item.found:
            return item

    output.fail(
        _("ecosystem.nothing_installed", domain=group_name(domain_key))
        + " "
        + _("adapters.override_hint", domain=domain_key, cap="<capability>", field="<field>")
    )
    raise typer.Exit(1)  # unreachable


# -- graph parsing (ros2 node info / ros2 topic info -v) ------------------


def parse_node_info(text: str) -> dict[str, dict[str, str]]:
    """``ros2 node info`` output → ``{section: {endpoint: type}}``."""
    sections: dict[str, dict[str, str]] = {}
    current: str | None = None
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        indent = len(line) - len(line.lstrip())
        if stripped.endswith(":") and indent <= 2:
            name = stripped[:-1]
            current = name if name in NODE_SECTIONS else None
            if current:
                sections.setdefault(current, {})
            continue
        if current and indent >= 4 and ":" in stripped:
            endpoint, _, kind = stripped.partition(":")
            sections[current][endpoint.strip()] = kind.strip()
    return sections


def parse_topic_qos(text: str) -> tuple[str | None, list[dict[str, str]]]:
    """``ros2 topic info -v`` output → (type, [endpoint dicts])."""
    topic_type: str | None = None
    endpoints: list[dict[str, str]] = []
    current: dict[str, str] | None = None
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or ":" not in stripped:
            continue
        key, _, value = stripped.partition(":")
        key, value = key.strip(), value.strip()
        if key == "Type" and current is None:
            topic_type = value
        elif key == "Node name":
            current = {"node": value}
            endpoints.append(current)
        elif current is None:
            continue
        elif key == "Endpoint type":
            current["endpoint"] = value
        elif key == "Reliability":
            current["reliability"] = value
        elif key == "Durability":
            current["durability"] = value
    return topic_type, endpoints


def node_interfaces(node: str) -> dict[str, dict[str, str]]:
    """Interfaces of one running node (empty when it is not reachable)."""
    result = ros_core.run_ros2(["node", "info", node])
    if not result.ok:
        return {}
    return parse_node_info(result.stdout)


def topic_qos(topic: str) -> tuple[str | None, list[dict[str, str]]]:
    """QoS endpoints of one topic (``ros2 topic info -v``)."""
    result = ros_core.run_ros2(["topic", "info", "-v", topic])
    if not result.ok:
        return None, []
    return parse_topic_qos(result.stdout)


def qos_mismatches(endpoints: list[dict[str, str]]) -> list[dict[str, str]]:
    """Incompatible pub/sub QoS pairs (the DDS compatibility rules)."""
    publishers = [e for e in endpoints if e.get("endpoint") == "PUBLISHER"]
    subscribers = [e for e in endpoints if e.get("endpoint") == "SUBSCRIPTION"]
    problems: list[dict[str, str]] = []
    for pub in publishers:
        for sub in subscribers:
            if (
                pub.get("reliability") == "BEST_EFFORT"
                and sub.get("reliability") == "RELIABLE"
            ):
                problems.append(
                    {
                        "publisher": pub.get("node", "?"),
                        "subscriber": sub.get("node", "?"),
                        "reason": _("ecosystem.qos.reliability"),
                    }
                )
            elif (
                pub.get("durability") == "VOLATILE"
                and sub.get("durability") == "TRANSIENT_LOCAL"
            ):
                problems.append(
                    {
                        "publisher": pub.get("node", "?"),
                        "subscriber": sub.get("node", "?"),
                        "reason": _("ecosystem.qos.durability"),
                    }
                )
    return problems


def echo_interfaces(node: str, sections: dict[str, dict[str, str]], with_qos: bool) -> None:
    """Print one node's interfaces (and the QoS of the topics it uses)."""
    output.echo(f"[bold]{node}[/bold]")
    for section in NODE_SECTIONS:
        entries = sections.get(section) or {}
        if not entries:
            continue
        output.echo(f"  [dim]{_(SECTION_LABELS[section])}[/dim]")
        for endpoint, kind in entries.items():
            output.echo(f"    {endpoint} [dim]{kind}[/dim]")
            if not with_qos or section not in ("Subscribers", "Publishers"):
                continue
            _topic_type, qos = topic_qos(endpoint)
            for entry in qos:
                output.echo(
                    "      [dim]"
                    + _(
                        "ecosystem.qos.row",
                        endpoint=entry.get("endpoint", "?").lower(),
                        node=entry.get("node", "?"),
                        reliability=entry.get("reliability", "?"),
                        durability=entry.get("durability", "?"),
                    )
                    + "[/dim]"
                )


def is_accelerated(node: str) -> bool:
    """Whether a node name marks it as GPU-accelerated."""
    lowered = node.lower()
    return any(token in lowered for token in ACCELERATED_TOKENS)


def graph_findings(nodes: list[str] | None = None, with_qos: bool = True) -> dict[str, Any]:
    """What the *running* graph says about acceleration.

    Only genuinely computable signals: a plain type used where an accelerated
    one exists, a boundary where an accelerated node talks to a plain one (a
    CPU↔GPU copy), and incompatible pub/sub QoS. Nothing is estimated.
    """
    listed = live_nodes() if nodes is None else nodes
    publishers: dict[str, list[tuple[str, str]]] = {}
    subscribers: dict[str, list[tuple[str, str]]] = {}
    for node in listed:
        sections = node_interfaces(node)
        for topic, kind in (sections.get("Publishers") or {}).items():
            publishers.setdefault(topic, []).append((node, kind))
        for topic, kind in (sections.get("Subscribers") or {}).items():
            subscribers.setdefault(topic, []).append((node, kind))

    types: dict[str, str] = {}
    for mapping in (publishers, subscribers):
        for topic, pairs in mapping.items():
            for _node, kind in pairs:
                types.setdefault(topic, kind)

    plain: list[dict[str, Any]] = []
    boundaries: list[dict[str, Any]] = []
    for topic in sorted(types):
        kind = types[topic]
        if kind not in NITROS_TYPES:
            continue
        ends = [*publishers.get(topic, []), *subscribers.get(topic, [])]
        names = sorted({node for node, _kind in ends})
        gpu = [node for node in names if is_accelerated(node)]
        cpu = [node for node in names if not is_accelerated(node)]
        if not gpu:
            continue
        plain.append(
            {"topic": topic, "type": kind, "accelerated_type": NITROS_TYPES[kind], "nodes": names}
        )
        if cpu:
            boundaries.append(
                {"topic": topic, "type": kind, "accelerated": gpu, "plain": cpu}
            )

    qos: list[dict[str, Any]] = []
    if with_qos:
        for topic in sorted(set(publishers) & set(subscribers)):
            for problem in qos_mismatches(topic_qos(topic)[1]):
                qos.append({"topic": topic, **problem})

    return {
        "nodes": listed,
        "accelerated": [node for node in listed if is_accelerated(node)],
        "topics": len(types),
        "plain": plain,
        "boundaries": boundaries,
        "qos": qos,
    }


# -- shared command bodies ------------------------------------------------

def status_payload(domain_key: str, extra: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = adapter(domain_key).status(state.cfg())
    running = running_capabilities(domain_key)
    payload["running"] = sorted(running)
    for item in payload["capabilities"]:
        item["nodes"] = running.get(item["key"], [])
    payload.update(extra or {})
    return payload


def echo_status(
    domain_key: str, json_output: bool, extra: dict[str, Any] | None = None
) -> None:
    payload = status_payload(domain_key, extra)
    if output.wants_json(json_output):
        output.echo_json(payload)
        return

    spec = domain_or_fail(domain_key)
    output.echo(f"[bold]{_(spec.title)}[/bold]")
    for key, value in payload.items():
        label_key = ROW_LABELS.get(key)
        if label_key is None or value in (None, ""):
            continue
        shown = value
        if isinstance(value, bool):
            shown = _("ecosystem.yes") if value else _("ecosystem.no")
        output.echo(f"  {_(label_key):<14} {shown}")

    table = Table(header_style="bold", **output.table_styles())
    table.add_column(_("ecosystem.col.capability"))
    table.add_column(_("ecosystem.col.state"))
    table.add_column(_("ecosystem.col.detail"))
    for item in payload["capabilities"]:
        table.add_row(item["key"], _state(item), item["value"] or _("ecosystem.not_installed"))
    output.echo(table)
    output.echo(
        f"[dim]{_('ecosystem.summary', installed=payload['installed'], total=payload['total'])}[/dim]"
    )


def _state(item: dict[str, Any]) -> str:
    if item.get("nodes"):
        return f"[green]{_('ecosystem.state.running')}[/green]"
    if item.get("found"):
        return f"[green]{_('ecosystem.state.installed')}[/green]"
    if item.get("core"):
        return f"[red]{_('ecosystem.state.missing')}[/red]"
    return f"[dim]{_('ecosystem.state.absent')}[/dim]"


def echo_catalog(domain_key: str, json_output: bool) -> None:
    """The ``list`` command: which capability is installed and which group wraps it."""
    cfg = state.cfg()
    items = catalog.resolve_domain(domain_key, cfg)
    payload = [
        {
            "capability": item.capability.key,
            "packages": list(item.capability.packages),
            "installed": item.found,
            "prefix": item.value,
            "group": item.capability.group,
            "launch": list(item.launch) if item.launch else None,
        }
        for item in items
    ]
    if output.wants_json(json_output):
        output.echo_json({"domain": domain_key, "capabilities": payload})
        return

    domain_or_fail(domain_key)
    table = Table(header_style="bold", **output.table_styles())
    table.add_column(_("ecosystem.col.capability"))
    table.add_column(_("ecosystem.col.packages"))
    table.add_column(_("ecosystem.col.installed"))
    table.add_column(_("ecosystem.col.prefix"))
    table.add_column(_("ecosystem.col.group"))
    for item, row in zip(items, payload):
        symbol, style = output.status_symbol("ok" if item.found else "skip")
        table.add_row(
            item.capability.key,
            ", ".join(item.capability.packages) or "—",
            f"[{style}]{symbol}[/]",
            row["prefix"] or "—",
            row["group"] or "—",
        )
    output.echo(table)
    output.echo(f"[dim]{_('ecosystem.list_hint', domain=domain_key)}[/dim]")


def render_checks(
    payload: dict[str, Any],
    results: list[CheckResult],
    verbose: bool,
    json_output: bool,
) -> None:
    """Print check results and exit 1 when any of them failed."""
    exit_code = 1 if any(result.status == "fail" for result in results) else 0
    if output.wants_json(json_output):
        output.echo_json(
            {
                **payload,
                "checks": [result.to_dict() for result in results],
                "exit_code": exit_code,
            }
        )
        raise typer.Exit(exit_code)

    for result in results:
        symbol, style = output.status_symbol(result.status)
        detail = f" — {result.detail}" if result.detail else ""
        output.echo(f"[{style}]{symbol}[/] {result.name}{detail}")
        if result.hint and (verbose or result.status in ("fail", "warn")):
            output.echo(f"    [dim]↳ {result.hint}[/dim]")
    raise typer.Exit(exit_code)


def echo_checks(
    domain_key: str,
    verbose: bool,
    json_output: bool,
    extra: list[CheckResult] | None = None,
) -> None:
    """The ``doctor`` command: the domain's checks plus anything the group adds."""
    sections = list(DOCTOR_SECTIONS.get(domain_key) or (adapter(domain_key).section(),))
    results = run_checks(sections, state.cfg())
    results.extend(extra or [])
    render_checks({"domain": domain_key, "sections": sections}, results, verbose, json_output)


def echo_started(record: runs.RunRecord, json_output: bool) -> None:
    if output.wants_json(json_output):
        output.echo_json(record.to_dict())
        return
    output.echo(f"[green]{_('ros.started', id=record.run_id)}[/green]")
    output.echo(f"  [dim]{_('sim.run.watch', id=record.run_id)}[/dim]")


def start_command(
    command: list[str],
    env: dict[str, str] | None = None,
    *,
    name: str,
    kind: str,
    backend: str = "ros",
    cwd: Path | None = None,
    dry_run: bool = False,
    json_output: bool = False,
    extra: dict[str, Any] | None = None,
    note: str | None = None,
    report: bool = False,
) -> None:
    """Echo a dry run, or start *command* as a detached tracked run."""
    if dry_run:
        output.echo(f"[bold]{_('replay.dry_title')}[/bold]")
        output.echo(f"  command: {' '.join(str(part) for part in command)}")
        if cwd is not None:
            output.echo(f"  cwd:     {cwd}")
        if note:
            output.echo(f"  [dim]{note}[/dim]")
        return
    record = runs.start_run(
        state.cfg(),
        name=name,
        command=command,
        cwd=cwd,
        env=env or None,
        backend=backend,
        kind=kind,
        extra=extra,
    )
    echo_started(record, json_output)
    if report and not output.wants_json(json_output):
        output.echo(f"  [dim]{_('benchmark.report_hint', id=record.run_id)}[/dim]")


def exec_pass_through(
    command: list[str], env: dict[str, str] | None = None, *, json_output: bool = False
) -> None:
    """Run *command* in the foreground, mirroring its exit code.

    The ``caasi native`` convention: output is captured and re-printed so the
    command still works in scripts and pipes.
    """
    result = shell.run_cmd(command, timeout=None, env=env or None)
    exit_code = result.returncode if result.returncode >= 0 else 1
    if output.wants_json(json_output):
        output.echo_json(
            {
                "command": [str(part) for part in command],
                "returncode": result.returncode,
                "stdout": result.stdout,
                "stderr": result.stderr,
            }
        )
        raise typer.Exit(exit_code)
    if result.stdout:
        output.echo(result.stdout.rstrip(), markup=False)
    if result.stderr:
        output.echo(result.stderr.rstrip(), markup=False)
    raise typer.Exit(exit_code)


def start_capability(
    domain_key: str,
    cap_key: str | None = None,
    extra_args: list[str] | None = None,
    *,
    name: str | None = None,
    kind: str | None = None,
    dry_run: bool = False,
    json_output: bool = False,
) -> None:
    """Resolve a capability and start it as a tracked run."""
    item = pick_capability(domain_key, cap_key)
    try:
        command, env = adapter(domain_key).command(
            state.cfg(), item.capability.key, list(extra_args or [])
        )
    except adapters.AdapterError as exc:
        output.fail(str(exc))
        return
    start_command(
        command,
        env,
        name=name or item.capability.key,
        kind=kind or domain_key,
        dry_run=dry_run,
        json_output=json_output,
        extra={"domain": domain_key, "capability": item.capability.key},
    )


def start_raw_launch(
    package: str,
    launch_file: str,
    extra_args: list[str] | None = None,
    *,
    kind: str = "isaacros",
    name: str | None = None,
    dry_run: bool = False,
    json_output: bool = False,
) -> None:
    """``ros2 launch <package> <file>`` as a tracked run."""
    binary = binary_or_fail()
    command = [binary, "launch", package, launch_file, *(extra_args or [])]
    start_command(
        command,
        launch_env(),
        name=name or launch_file,
        kind=kind,
        dry_run=dry_run,
        json_output=json_output,
        extra={"package": package, "launch": launch_file},
    )


def sample_rate(topic: str, window: int = 10, duration: float = 5.0) -> dict[str, Any]:
    """Bounded ``ros2 topic hz`` sample: {"topic", "rate", "detail"}."""
    binary = ros_core.find_ros2_binary()
    if not binary:
        return {"topic": topic, "rate": None, "detail": _("native.no_ros2")}
    command, _bounded = with_duration(
        rosenv.wrap([binary, "topic", "hz", "--window", str(window), topic]), duration
    )
    result = shell.run_cmd(command, timeout=duration + 5.0)
    rate = None
    for line in result.stdout.splitlines():
        if "average rate" in line:
            try:
                rate = float(line.split("average rate:")[1].strip())
            except (IndexError, ValueError):
                rate = None
            break
    detail = _("ecosystem.rate.none") if rate is None else _("ecosystem.rate.value", rate=rate)
    return {"topic": topic, "rate": rate, "detail": detail}


# -- the factory ----------------------------------------------------------


def build_group(
    domain_key: str,
    *,
    status_extra: Callable[[], dict[str, Any]] | None = None,
    doctor_extra: Callable[[], list[CheckResult]] | None = None,
) -> typer.Typer:
    """Build the shared commands of a catalog-driven group.

    ``status`` is always generated; ``list`` / ``doctor`` / the run verb follow
    the domain's ``verbs`` in the catalog. Group-specific commands are added by
    the caller on the returned app.
    """
    app = typer.Typer(no_args_is_help=True)
    spec = catalog.domain(domain_key)
    verbs = spec.verbs if spec else ()
    title = _(spec.title) if spec else domain_key

    @app.command("status", help=_("ecosystem.status_help", domain=title))
    def status_command(
        json_output: bool = typer.Option(False, "--json", help=_("flag.json")),
    ) -> None:
        echo_status(domain_key, json_output, status_extra() if status_extra else None)

    if "list" in verbs:

        @app.command("list", help=_("ecosystem.list_help", domain=title))
        def list_command(
            json_output: bool = typer.Option(False, "--json", help=_("flag.json")),
        ) -> None:
            echo_catalog(domain_key, json_output)

    if "doctor" in verbs:

        @app.command("doctor", help=_("ecosystem.doctor_help", domain=title))
        def doctor_command(
            verbose: bool = typer.Option(False, "--verbose", help=_("ecosystem.flag.verbose")),
            json_output: bool = typer.Option(False, "--json", help=_("flag.json")),
        ) -> None:
            echo_checks(
                domain_key,
                verbose,
                json_output,
                doctor_extra() if doctor_extra else None,
            )

    run_verb = next((verb for verb in RUN_VERBS if verb in verbs), None)
    if run_verb == "launch" and domain_key == "isaacros":

        @app.command(
            "launch", help=_("isaacros.launch_help"), context_settings=EXTRA_SETTINGS
        )
        def isaacros_launch(
            ctx: typer.Context,
            package: str = typer.Argument(..., help=_("isaacros.arg.package")),
            launch_file: str = typer.Argument(..., help=_("isaacros.arg.launch_file")),
            name: Optional[str] = typer.Option(None, "--name", help=_("ecosystem.flag.name")),
            dry_run: bool = typer.Option(False, "--dry-run", help=_("ecosystem.flag.dry_run")),
            json_output: bool = typer.Option(False, "--json", help=_("flag.json")),
        ) -> None:
            start_raw_launch(
                package,
                launch_file,
                [str(arg) for arg in ctx.args],
                name=name,
                dry_run=dry_run,
                json_output=json_output,
            )

    elif run_verb:

        @app.command(
            run_verb,
            help=_("ecosystem.run_help", domain=title, verb=run_verb),
            context_settings=EXTRA_SETTINGS,
        )
        def capability_run(
            ctx: typer.Context,
            backend: Optional[str] = typer.Option(
                None, "--backend", "-b", help=_("ecosystem.flag.backend", domain=domain_key)
            ),
            name: Optional[str] = typer.Option(None, "--name", help=_("ecosystem.flag.name")),
            dry_run: bool = typer.Option(False, "--dry-run", help=_("ecosystem.flag.dry_run")),
            json_output: bool = typer.Option(False, "--json", help=_("flag.json")),
        ) -> None:
            start_capability(
                domain_key,
                backend,
                [str(arg) for arg in ctx.args],
                name=name,
                dry_run=dry_run,
                json_output=json_output,
            )

    return app
