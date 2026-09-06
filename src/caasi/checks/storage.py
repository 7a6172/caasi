"""Storage check: free disk space on the runs directory."""

from __future__ import annotations

from pathlib import Path

from ..i18n import _
from ..utils import sysinfo
from . import CheckResult, register

WARN_BYTES = 20 * 1024**3
FAIL_BYTES = 5 * 1024**3


@register("storage")
def check_storage(ctx) -> list[CheckResult]:
    runs = ctx.config.expanded_path_for("paths.runs") or Path.home() / ".isaac" / "runs"
    usage = sysinfo.disk_usage(sysinfo.existing_ancestor(runs))
    if usage is None:
        return [
            CheckResult("storage", _("doctor.storage.title"), "warn", _("doctor.storage.unknown"))
        ]

    detail = _("doctor.storage.detail").format(
        free=sysinfo.human_bytes(usage.free), path=str(runs)
    )
    if usage.free < FAIL_BYTES:
        return [
            CheckResult(
                "storage", _("doctor.storage.title"), "fail", detail, _("doctor.storage.hint")
            )
        ]
    if usage.free < WARN_BYTES:
        return [
            CheckResult(
                "storage", _("doctor.storage.title"), "warn", detail, _("doctor.storage.hint")
            )
        ]
    return [CheckResult("storage", _("doctor.storage.title"), "ok", detail)]
