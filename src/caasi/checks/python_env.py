"""Python environment checks."""

from __future__ import annotations

import os
import platform
import sys

from ..i18n import _
from . import CheckResult, register

MINIMUM = (3, 10)


@register("python")
def check_python(ctx) -> list[CheckResult]:
    results: list[CheckResult] = []
    version = platform.python_version()
    if sys.version_info[:2] >= MINIMUM:
        results.append(
            CheckResult(
                "python", _("doctor.python.version"), "ok", f"Python {version} ({sys.executable})"
            )
        )
    else:
        results.append(
            CheckResult(
                "python",
                _("doctor.python.version"),
                "fail",
                f"Python {version}",
                _("doctor.python.version_hint"),
            )
        )

    conda_env = os.environ.get("CONDA_DEFAULT_ENV")
    if conda_env:
        results.append(
            CheckResult(
                "python", _("doctor.python.env"), "ok", _("doctor.python.conda").format(env=conda_env)
            )
        )
    elif sys.prefix != sys.base_prefix:
        results.append(
            CheckResult("python", _("doctor.python.env"), "ok", _("doctor.python.venv"))
        )
    else:
        results.append(
            CheckResult("python", _("doctor.python.env"), "skip", _("doctor.python.system_env"))
        )
    return results
