"""Vision stack checks: OpenCV, Open3D (metadata only)."""

from __future__ import annotations

from ..i18n import _
from ..utils import pydist
from . import CheckResult, register


@register("vision")
def check_vision(ctx) -> list[CheckResult]:
    results: list[CheckResult] = []

    cv = pydist.pip_version("opencv-python", "opencv-python-headless", "opencv-contrib-python")
    if cv:
        results.append(CheckResult("vision", _("doctor.vision.opencv"), "ok", cv))
    else:
        results.append(
            CheckResult(
                "vision",
                _("doctor.vision.opencv"),
                "fail",
                _("doctor.vision.not_installed"),
                _("doctor.vision.opencv_hint"),
            )
        )

    o3d = pydist.pip_version("open3d", "open3d-cpu")
    if o3d:
        results.append(CheckResult("vision", _("doctor.vision.open3d"), "ok", o3d))
    else:
        results.append(
            CheckResult(
                "vision",
                _("doctor.vision.open3d"),
                "fail",
                _("doctor.vision.not_installed"),
                _("doctor.vision.open3d_hint"),
            )
        )
    return results
