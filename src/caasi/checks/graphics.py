"""Graphics checks: Vulkan availability, display server."""

from __future__ import annotations

import os

from ..i18n import _
from ..utils import shell
from . import CheckResult, register


@register("graphics")
def check_graphics(ctx) -> list[CheckResult]:
    results: list[CheckResult] = []

    if shell.which("vulkaninfo"):
        results.append(CheckResult("graphics", _("doctor.graphics.vulkan"), "ok", "vulkaninfo"))
    else:
        ld = shell.run_cmd(["ldconfig", "-p"], timeout=5)
        if ld.ok and "libvulkan" in ld.stdout:
            results.append(
                CheckResult(
                    "graphics", _("doctor.graphics.vulkan"), "ok", _("doctor.graphics.vulkan_lib")
                )
            )
        else:
            results.append(
                CheckResult(
                    "graphics",
                    _("doctor.graphics.vulkan"),
                    "warn",
                    _("doctor.graphics.vulkan_missing"),
                    _("doctor.graphics.vulkan_hint"),
                )
            )

    if os.environ.get("WAYLAND_DISPLAY") or os.environ.get("DISPLAY"):
        results.append(
            CheckResult("graphics", _("doctor.graphics.display"), "ok", _("doctor.graphics.display_on"))
        )
    else:
        results.append(
            CheckResult(
                "graphics",
                _("doctor.graphics.display"),
                "skip",
                _("doctor.graphics.display_off"),
            )
        )
    return results
