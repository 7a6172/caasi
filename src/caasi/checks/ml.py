"""ML stack checks: PyTorch, TensorRT, ONNX Runtime, cuDNN (metadata only)."""

from __future__ import annotations

from ..i18n import _
from ..utils import pydist, shell
from . import CheckResult, register


def _pip_check(section: str, name_key: str, dists: tuple[str, ...], hint_key: str) -> CheckResult:
    version = pydist.pip_version(*dists)
    if version:
        return CheckResult(section, _(name_key), "ok", version)
    return CheckResult(section, _(name_key), "fail", _("doctor.ml.not_installed"), _(hint_key))


@register("ml")
def check_ml(ctx) -> list[CheckResult]:
    results = [
        _pip_check("ml", "doctor.ml.torch", ("torch",), "doctor.ml.torch_hint"),
        _pip_check("ml", "doctor.ml.tensorrt", ("tensorrt", "tensorrt_libs"), "doctor.ml.tensorrt_hint"),
        _pip_check(
            "ml", "doctor.ml.onnx", ("onnxruntime-gpu", "onnxruntime"), "doctor.ml.onnx_hint"
        ),
    ]

    cudnn = pydist.pip_version("nvidia-cudnn-cu12", "nvidia-cudnn-cu11")
    if cudnn:
        results.append(CheckResult("ml", _("doctor.ml.cudnn"), "ok", cudnn))
    else:
        ld = shell.run_cmd(["ldconfig", "-p"], timeout=5)
        if ld.ok and "libcudnn" in ld.stdout:
            results.append(
                CheckResult("ml", _("doctor.ml.cudnn"), "ok", _("doctor.ml.cudnn_system"))
            )
        else:
            results.append(
                CheckResult(
                    "ml", _("doctor.ml.cudnn"), "warn", _("doctor.ml.not_installed"), _("doctor.ml.cudnn_hint")
                )
            )
    return results
