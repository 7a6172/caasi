"""NVIDIA checks: driver, GPUs, CUDA (via nvidia-smi)."""

from __future__ import annotations

from ..core import nvidia
from ..i18n import _
from . import CheckResult, register


@register("nvidia")
def check_nvidia(ctx) -> list[CheckResult]:
    if not nvidia.available():
        return [
            CheckResult(
                "nvidia",
                _("doctor.nvidia.smi"),
                "fail",
                _("doctor.nvidia.smi_missing_detail"),
                _("doctor.nvidia.smi_hint"),
            )
        ]

    results: list[CheckResult] = []
    try:
        gpus = nvidia.query(["index", "name", "memory.total", "driver_version"])
    except nvidia.NvidiaSmiError as exc:
        return [
            CheckResult(
                "nvidia",
                _("doctor.nvidia.smi"),
                "fail",
                str(exc),
                _("doctor.nvidia.smi_hint"),
            )
        ]

    driver = gpus[0].get("driver_version") if gpus else None
    results.append(
        CheckResult(
            "nvidia",
            _("doctor.nvidia.driver"),
            "ok",
            _("doctor.nvidia.driver_detail").format(driver=driver or "?"),
        )
    )
    for gpu in gpus:
        vram = gpu.get("memory.total")
        detail = _("doctor.nvidia.gpu_detail").format(
            name=gpu.get("name", "?"),
            vram=f"{vram / 1024:.1f} GiB" if isinstance(vram, (int, float)) else "?",
        )
        results.append(CheckResult("nvidia", _("doctor.nvidia.gpu"), "ok", detail))

    cuda = nvidia.cuda_version()
    if cuda:
        results.append(
            CheckResult(
                "nvidia",
                _("doctor.nvidia.cuda"),
                "ok",
                _("doctor.nvidia.cuda_detail").format(version=cuda),
            )
        )
    else:
        results.append(
            CheckResult(
                "nvidia", _("doctor.nvidia.cuda"), "warn", "", _("doctor.nvidia.cuda_hint")
            )
        )
    return results
