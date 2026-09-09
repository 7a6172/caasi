"""ROS 2 discovery and delegation helpers.

The CLI never speaks rclpy — every ROS 2 operation is delegated to the real
``ros2`` CLI via subprocess, so caasi stays a thin orchestration layer.
"""

from __future__ import annotations

import os
from pathlib import Path

from ..utils import shell

ROS_ROOT = Path("/opt/ros")

DEFAULT_TIMEOUT = 20.0


class RosError(RuntimeError):
    """Raised when the ros2 CLI itself is unavailable."""


def find_distro() -> tuple[str | None, Path | None]:
    """Return (distro name, root path) using ROS_DISTRO first, then /opt/ros scan."""
    distro = os.environ.get("ROS_DISTRO")
    if distro:
        root = ROS_ROOT / distro
        return distro, (root if root.is_dir() else None)
    if ROS_ROOT.is_dir():
        try:
            entries = sorted(ROS_ROOT.iterdir())
        except OSError:
            return None, None
        for entry in entries:
            if entry.is_dir() and (entry / "setup.bash").exists():
                return entry.name, entry
    return None, None


def find_ros2_binary() -> str | None:
    """Locate the ros2 CLI (distro bin first, then PATH)."""
    _, root = find_distro()
    if root is not None:
        candidate = root / "bin" / "ros2"
        if candidate.exists():
            return str(candidate)
    return shell.which("ros2")


def require_ros2() -> str:
    """Return the ros2 binary path or raise :class:`RosError`."""
    binary = find_ros2_binary()
    if not binary:
        from ..i18n import _

        raise RosError(_("native.no_ros2"))
    return binary


def run_ros2(
    args: list[str], timeout: float | None = DEFAULT_TIMEOUT
) -> shell.ShellResult:
    """Run ``ros2 <args>`` capturing output.

    The command is wrapped so that it works in an unsourced shell too (see
    :mod:`caasi.core.rosenv`); in an already-sourced shell the wrapper is a
    no-op and the plain binary is executed.

    Raises :class:`RosError` only when the ros2 binary is missing; failing
    ros2 calls are reported through the returned ShellResult.
    """
    from . import rosenv

    binary = require_ros2()
    return shell.run_cmd(rosenv.wrap([binary, *args]), timeout=timeout)


def ros2_lines(
    args: list[str], timeout: float | None = DEFAULT_TIMEOUT
) -> list[str]:
    """Run a ros2 command and return its non-empty stdout lines."""
    result = run_ros2(args, timeout=timeout)
    if not result.ok:
        return []
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def pkg_prefix(name: str) -> Path | None:
    """Return the install prefix of a ROS package, if installed."""
    result = run_ros2(["pkg", "prefix", name], timeout=DEFAULT_TIMEOUT)
    text = result.stdout.strip()
    if not result.ok or not text:
        return None
    path = Path(text)
    return path if path.is_dir() else None
