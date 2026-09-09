"""ROS 2 checks: distro, setup file, ros2 CLI, sourced environment, middleware."""

from __future__ import annotations

import os

from ..core import ros as ros_core
from ..core import rosenv
from ..i18n import _
from . import CheckResult, register


@register("ros")
def check_ros(ctx) -> list[CheckResult]:
    distro, root = ros_core.find_distro()
    if distro is None:
        return [
            CheckResult(
                "ros",
                _("doctor.ros.distro"),
                "fail",
                _("doctor.ros.missing"),
                _("doctor.ros.hint"),
            )
        ]

    results: list[CheckResult] = []
    results.append(CheckResult("ros", _("doctor.ros.distro"), "ok", distro))

    if root is not None and (root / "setup.bash").exists():
        results.append(
            CheckResult(
                "ros", _("doctor.ros.setup"), "ok", str(root / "setup.bash")
            )
        )
    else:
        results.append(
            CheckResult(
                "ros",
                _("doctor.ros.setup"),
                "warn",
                _("doctor.ros.setup_missing").format(distro=distro),
                _("doctor.ros.setup_hint"),
            )
        )

    ros2 = ros_core.find_ros2_binary()
    if ros2:
        results.append(CheckResult("ros", _("doctor.ros.cli"), "ok", ros2))
    else:
        results.append(
            CheckResult(
                "ros", _("doctor.ros.cli"), "warn", _("doctor.ros.cli_missing"), _("doctor.ros.hint")
            )
        )

    if rosenv.is_sourced():
        results.append(
            CheckResult("ros", _("doctor.ros.sourced"), "ok", _("doctor.ros.sourced_ok"))
        )
    elif rosenv.setup_file() is not None:
        results.append(
            CheckResult(
                "ros",
                _("doctor.ros.sourced"),
                "warn",
                _("doctor.ros.sourced_missing"),
                _("doctor.ros.sourced_hint", command=rosenv.source_hint()),
            )
        )
    else:
        results.append(
            CheckResult(
                "ros", _("doctor.ros.sourced"), "skip", _("doctor.ros.sourced_unknown")
            )
        )

    rmw = os.environ.get("RMW_IMPLEMENTATION")
    if rmw:
        results.append(CheckResult("ros", _("doctor.ros.rmw"), "ok", rmw))
    else:
        results.append(
            CheckResult("ros", _("doctor.ros.rmw"), "skip", _("doctor.ros.rmw_default"))
        )
    return results
