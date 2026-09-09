"""Robotics stack checks: Nav2, MoveIt 2, ros2_control (best-effort via ros2 CLI)."""

from __future__ import annotations

from ..core import ros as ros_core
from ..i18n import _
from ..utils import shell
from . import CheckResult, register

STACKS = [
    ("nav2", "nav2_bringup", "doctor.robotics.nav2"),
    ("moveit2", "moveit_core", "doctor.robotics.moveit"),
    ("ros2_control", "controller_manager", "doctor.robotics.control"),
    ("slam", "slam_toolbox", "doctor.robotics.slam"),
]

PKG_TIMEOUT = 8.0


@register("robotics")
def check_robotics(ctx) -> list[CheckResult]:
    ros2 = ros_core.find_ros2_binary()
    if not ros2:
        return [
            CheckResult(
                "robotics",
                _("doctor.robotics.title"),
                "skip",
                _("doctor.robotics.no_ros2"),
                _("doctor.robotics.no_ros2_hint"),
            )
        ]

    results: list[CheckResult] = []
    for stack, package, name_key in STACKS:
        probe = shell.run_cmd([ros2, "pkg", "prefix", package], timeout=PKG_TIMEOUT)
        if probe.ok:
            results.append(CheckResult("robotics", _(name_key), "ok", package))
        elif probe.returncode == -1:
            results.append(
                CheckResult(
                    "robotics", _(name_key), "warn", _("doctor.robotics.timeout").format(package=package)
                )
            )
        else:
            results.append(
                CheckResult(
                    "robotics",
                    _(name_key),
                    "fail",
                    _("doctor.robotics.not_installed").format(package=package),
                    _("doctor.robotics.hint").format(stack=stack),
                )
            )
    return results
