"""Project doctor section: is the current ``caasi.yaml`` well-formed?

Machine-capability verb (five-verb rule): this reports *structural* health of
the project the user is standing in — manifest parses, ``schema`` is understood,
``name`` is present, and every registered component's directories exist. It does
not resolve requirements against the machine (that is ``caasi check``). Skips
cleanly when run outside a project.
"""

from __future__ import annotations

from ..core import components, project
from ..core import manifest as manifests
from ..i18n import _
from . import CheckResult, register


@register("project")
def check_project(ctx) -> list[CheckResult]:
    root = project.find_project_root()
    if root is None:
        return [
            CheckResult(
                "project",
                _("doctor.project.title"),
                "skip",
                _("doctor.project.no_project"),
                _("doctor.project.no_project_hint"),
            )
        ]

    results: list[CheckResult] = []
    data = project.load_project_meta(root)
    if not data:
        return [
            CheckResult(
                "project",
                _("doctor.project.title"),
                "fail",
                _("doctor.project.unparsable", file=project.PROJECT_FILE),
                _("doctor.project.unparsable_hint"),
            )
        ]

    schema = data.get("schema")
    if schema == manifests.SCHEMA:
        results.append(
            CheckResult("project", _("doctor.project.schema"), "ok", str(schema))
        )
    else:
        results.append(
            CheckResult(
                "project",
                _("doctor.project.schema"),
                "warn",
                _("doctor.project.schema_unknown", schema=schema, known=manifests.SCHEMA),
                _("doctor.project.schema_hint"),
            )
        )

    name = data.get("name")
    if name:
        results.append(CheckResult("project", _("doctor.project.name"), "ok", str(name)))
    else:
        results.append(
            CheckResult(
                "project",
                _("doctor.project.name"),
                "warn",
                _("doctor.project.name_missing"),
                _("doctor.project.name_hint"),
            )
        )

    registered = manifests.read(root).registered()
    missing: list[str] = []
    for key in registered:
        for sub in components.dirs_for(key):
            if not (root / sub).is_dir():
                missing.append(f"{key}:{sub}")
    if missing:
        results.append(
            CheckResult(
                "project",
                _("doctor.project.components"),
                "warn",
                _("doctor.project.components_missing", count=len(missing)),
                _("doctor.project.components_hint", dirs=", ".join(missing)),
            )
        )
    else:
        detail = _("doctor.project.components_none")
        if registered:
            detail = ", ".join(registered)
        results.append(
            CheckResult("project", _("doctor.project.components"), "ok", detail)
        )

    return results
