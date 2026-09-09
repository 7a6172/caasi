"""Teleop backend selection + bag command builders (``plan3.md`` §24-25).

A thin bridge between the ``teleop`` catalog domain and the tools that
already exist: ``ros2 launch`` for the keyboard/joystick stacks, the
resolved Isaac Sim XR script, and ``ros2 bag record``/``play`` for
demonstrations. Caasi implements no teleoperation itself; recording
destinations follow :mod:`caasi.core.dataset`, so ``teleop record`` output
feeds ``dataset inspect`` / ``lab train`` directly (the §25 workflow).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..i18n import _
from . import catalog, ros, rosenv, runs

if TYPE_CHECKING:  # pragma: no cover
    from .config import Config

DOMAIN = "teleop"

#: Stacks ``teleop start`` prefers, in order; the catalog decides their names.
BACKENDS = ("keyboard", "joy", "xr")

#: Run kinds ``teleop stop`` terminates.
STOP_KINDS = ("teleop", "bag")


class TeleopError(RuntimeError):
    """Raised when a teleop command cannot be built."""


def launch_env() -> dict[str, str]:
    """Environment for a raw ``ros2`` command: empty when already sourced."""
    return {} if rosenv.is_sourced() else rosenv.sourced_env()


def pick_backend(config: "Config | None" = None, requested: str | None = None) -> catalog.Resolved:
    """The stack to start: request → ``catalog.teleop.default`` → first installed."""
    if requested is not None:
        item = catalog.resolve_capability(DOMAIN, requested, config)
        if item is None:
            known = ", ".join(cap.key for cap in catalog.capabilities(DOMAIN, config))
            raise TeleopError(
                _("ecosystem.unknown_backend", domain=DOMAIN, cap=requested, known=known)
            )
        if not item.found:
            raise TeleopError(
                _(
                    "adapters.missing",
                    domain=DOMAIN,
                    cap=requested,
                    targets=catalog.targets(item.capability),
                )
                + " "
                + _(
                    "adapters.override_hint",
                    domain=DOMAIN,
                    cap=requested,
                    field=catalog.override_field(item.capability),
                )
            )
        return item

    default = catalog.domain_setting(DOMAIN, "default", config)
    if default:
        item = catalog.resolve_capability(DOMAIN, str(default), config)
        if item is not None and item.found:
            return item

    for key in BACKENDS:
        item = catalog.resolve_capability(DOMAIN, key, config)
        if item is not None and item.found:
            return item

    raise TeleopError(
        _("ecosystem.nothing_installed", domain=DOMAIN)
        + " "
        + _("adapters.override_hint", domain=DOMAIN, cap="<capability>", field="<field>")
    )


def stack_command(
    item: catalog.Resolved,
    config: "Config | None" = None,
    *,
    device: str | None = None,
    extra: list[str] | None = None,
) -> tuple[list[str], dict[str, str]]:
    """(command, env) that starts a resolved teleop stack.

    Launch-file stacks run through ``ros2 launch`` (``--device`` becomes the
    launch argument ``device:=<path>``); a resolved script such as Isaac Sim's
    ``isaac-sim.xr.vr.sh`` runs directly.
    """
    args = [str(a) for a in (extra or [])]
    if item.launch:
        binary = ros.require_ros2()
        package, launch_file = item.launch
        if device:
            args.insert(0, f"device:={device}")
        return [binary, "launch", package, launch_file, *args], launch_env()
    if item.how in ("binary", "path") and item.value:
        if device:
            args.insert(0, str(device))
        return [str(item.value), *args], {}
    raise TeleopError(_("adapters.no_launch", domain=DOMAIN, cap=item.capability.key))


def record_command(
    binary: str, topics: list[str], dest, extra: list[str] | None = None
) -> list[str]:
    """``ros2 bag record`` into *dest* (all topics when *topics* is empty)."""
    recorded = [str(topic) for topic in topics] or ["-a"]
    return [
        binary, "bag", "record", *recorded, "-o", str(dest),
        *[str(a) for a in (extra or [])],
    ]


def play_command(binary: str, bag, extra: list[str] | None = None) -> list[str]:
    return [binary, "bag", "play", str(bag), *[str(a) for a in (extra or [])]]


def record_metadata(
    name: str, created: str, run_id: str, topics: list[str]
) -> dict[str, object]:
    """``metadata.json`` for a demonstration recording (the §25 bridge)."""
    return {
        "name": name,
        "created": created,
        "kind": "teleop",
        "topics": topics,
        "status": "recording",
        "run_id": run_id,
    }


def active_runs(config: "Config") -> list[runs.RunRecord]:
    """Running/paused teleop and bag-recording runs, newest first."""
    return [
        record
        for record in runs.list_runs(config)
        if record.kind in STOP_KINDS
        and runs.effective_status(record) in (runs.RUNNING, runs.PAUSED)
    ]
