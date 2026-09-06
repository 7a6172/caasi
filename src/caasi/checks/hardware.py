"""Hardware checks: CPU, RAM."""

from __future__ import annotations

import os

from ..i18n import _
from ..utils import sysinfo
from . import CheckResult, register

RAM_WARN_KIB = 16 * 1024 * 1024  # below 16 GiB is tight for Isaac workflows


@register("hardware")
def check_hardware(ctx) -> list[CheckResult]:
    results: list[CheckResult] = []

    model = sysinfo.cpu_model()
    cores = os.cpu_count()
    if model or cores:
        detail = ", ".join(part for part in (model, f"{cores} cores") if part)
        results.append(CheckResult("hardware", _("doctor.hardware.cpu"), "ok", detail))
    else:
        results.append(
            CheckResult(
                "hardware", _("doctor.hardware.cpu"), "warn", "", _("doctor.hardware.cpu_hint")
            )
        )

    meminfo = sysinfo.read_meminfo()
    total_kib = meminfo.get("MemTotal")
    available_kib = meminfo.get("MemAvailable")
    if total_kib:
        detail = _("doctor.hardware.ram_detail").format(
            total=total_kib / (1024 * 1024),
            available=(available_kib or 0) / (1024 * 1024),
        )
        status = "ok" if total_kib >= RAM_WARN_KIB else "warn"
        hint = "" if status == "ok" else _("doctor.hardware.ram_hint")
        results.append(CheckResult("hardware", _("doctor.hardware.ram"), status, detail, hint))
    else:
        results.append(
            CheckResult(
                "hardware", _("doctor.hardware.ram"), "warn", "", _("doctor.hardware.ram_hint")
            )
        )
    return results
