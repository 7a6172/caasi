"""Alternative simulator checks: Gazebo, MuJoCo."""

from __future__ import annotations

from ..i18n import _
from ..utils import pydist, shell
from . import CheckResult, register


@register("simulators")
def check_simulators(ctx) -> list[CheckResult]:
    results: list[CheckResult] = []

    gz = shell.which("gz") or shell.which("gazebo")
    if gz:
        results.append(CheckResult("simulators", _("doctor.sims.gazebo"), "ok", gz))
    else:
        results.append(
            CheckResult(
                "simulators",
                _("doctor.sims.gazebo"),
                "skip",
                _("doctor.sims.not_installed"),
                _("doctor.sims.gazebo_hint"),
            )
        )

    mujoco = pydist.pip_version("mujoco")
    if mujoco:
        results.append(CheckResult("simulators", _("doctor.sims.mujoco"), "ok", mujoco))
    else:
        results.append(
            CheckResult(
                "simulators",
                _("doctor.sims.mujoco"),
                "skip",
                _("doctor.sims.not_installed"),
                _("doctor.sims.mujoco_hint"),
            )
        )
    return results
