"""Container runtime checks: docker, podman."""

from __future__ import annotations

from ..i18n import _
from ..utils import shell
from . import CheckResult, register


def _probe(name: str, binary: str, name_key: str) -> CheckResult:
    path = shell.which(binary)
    if not path:
        return CheckResult(name, _(name_key), "skip", _("doctor.containers.not_installed"))
    result = shell.run_cmd([binary, "--version"], timeout=5)
    if result.ok:
        return CheckResult(name, _(name_key), "ok", result.stdout.strip().splitlines()[0])
    return CheckResult(name, _(name_key), "warn", result.stderr.strip() or _("doctor.containers.error"))


@register("containers")
def check_containers(ctx) -> list[CheckResult]:
    docker = _probe("containers", "docker", "doctor.containers.docker")
    podman = _probe("containers", "podman", "doctor.containers.podman")
    results = [docker, podman]
    if docker.status == "skip" and podman.status == "skip":
        results.append(
            CheckResult(
                "containers",
                _("doctor.containers.title"),
                "warn",
                _("doctor.containers.none"),
                _("doctor.containers.hint"),
            )
        )
    return results
