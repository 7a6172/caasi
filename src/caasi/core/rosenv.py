"""Sourced-ROS execution.

``ros2`` only works when ``/opt/ros/<distro>/setup.bash`` has been sourced —
an unsourced shell crashes inside ``importlib.metadata`` rather than printing
a helpful error. Caasi therefore wraps ROS commands in a sourcing shell *only
when the current environment is not already sourced*, which is a no-op for
anyone running from a normal ROS terminal.
"""

from __future__ import annotations

import os
from pathlib import Path

from ..utils import shell
from . import ros

#: Markers that prove the ROS environment is already sourced.
SOURCE_MARKERS = ("AMENT_PREFIX_PATH", "COLCON_PREFIX_PATH", "PYTHONPATH")

ENV_TIMEOUT = 5.0

_env_cache: dict[str, dict[str, str]] = {}


def setup_file(distro: str | None = None) -> Path | None:
    """Return ``/opt/ros/<distro>/setup.bash`` when it exists."""
    name, root = ros.find_distro()
    if distro is not None:
        root = ros.ROS_ROOT / distro
    if root is None:
        return None
    candidate = root / "setup.bash"
    return candidate if candidate.is_file() else None


def ros_root(distro: str | None = None) -> Path | None:
    _, root = ros.find_distro()
    if distro is not None:
        root = ros.ROS_ROOT / distro
    return root


def is_sourced(distro: str | None = None) -> bool:
    """True when the environment already exposes the ROS install prefix."""
    root = ros_root(distro)
    if root is None:
        return False
    needle = str(root)
    return any(needle in os.environ.get(marker, "") for marker in SOURCE_MARKERS)


def sourced_env(distro: str | None = None) -> dict[str, str]:
    """Environment after sourcing ``setup.bash`` (cached; falls back to os.environ)."""
    setup = setup_file(distro)
    if setup is None:
        return dict(os.environ)

    cache_key = str(setup)
    if cache_key in _env_cache:
        return _env_cache[cache_key]

    result = shell.run_cmd(
        ["bash", "-c", f'source "{setup}" >/dev/null 2>&1 && env'], timeout=ENV_TIMEOUT
    )
    env = dict(os.environ)
    if result.ok:
        key: str | None = None
        for line in result.stdout.splitlines():
            name, sep, value = line.partition("=")
            if sep and name and not name[0].isdigit():
                key = name
                env[key] = value
            elif key is not None:
                env[key] += "\n" + line
    _env_cache[cache_key] = env
    return env


def wrap(command: list[str], distro: str | None = None) -> list[str]:
    """Return *command*, sourcing ROS first only when that is actually needed."""
    setup = setup_file(distro)
    if setup is None or is_sourced(distro):
        return list(command)
    return ["bash", "-c", f'source "{setup}" >/dev/null 2>&1 && exec "$@"', "--", *command]


def source_hint(distro: str | None = None) -> str:
    """The shell line a user needs to run (used by doctor hints)."""
    setup = setup_file(distro)
    return f"source {setup}" if setup else ""


def clear_cache() -> None:
    """Drop memoised environments (used by the test-suite)."""
    _env_cache.clear()
