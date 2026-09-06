"""System checks: operating system, kernel, architecture."""

from __future__ import annotations

import platform

from ..i18n import _
from ..utils import sysinfo
from . import CheckResult, register


@register("system")
def check_system(ctx) -> list[CheckResult]:
    results: list[CheckResult] = []
    system = platform.system()
    if system == "Linux":
        pretty = sysinfo.os_pretty_name()
        results.append(
            CheckResult("system", _("doctor.system.os"), "ok", pretty or "Linux")
        )
    else:
        results.append(
            CheckResult(
                "system",
                _("doctor.system.os"),
                "fail",
                system,
                _("doctor.system.os_hint"),
            )
        )
    uname = platform.uname()
    results.append(
        CheckResult(
            "system",
            _("doctor.system.kernel"),
            "ok",
            f"{uname.release} ({uname.machine})",
        )
    )
    return results
