"""Root ``caasi audit`` — account for a project and its reproducibility (§24-26).

The fifth verb. Where ``doctor`` asks "what's wrong with my machine?", ``check``
asks "can this work here?" and ``validate`` asks "is this structurally valid?",
``audit`` asks "can I *account for* this project and reproduce it?". One
semantic operation, six scopes::

    caasi audit                     every scope
    caasi audit project             manifest + working tree
    caasi audit dependencies        required/registered components detected
    caasi audit environment         fingerprint + GPU/CUDA + Python drift
    caasi audit files               directories + definition placement
    caasi audit runs                run records, logs, metrics, orphans
    caasi audit reproducibility     git + fingerprint + lock + provenance bundle

Each scope yields ✓/⚠/✗ findings folded into a ``N warnings, M errors`` result.
``--fix`` applies **only CAASI-owned safe fixes** (§26): it creates missing
CAASI directories and nothing else — never user source, packages, drivers,
upstream installs, ROS packages or Isaac installations. Exit 1 when any scope
reports an error, else 0 (warnings never fail an audit).
"""

from __future__ import annotations

import platform
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

import typer

from .. import state
from ..core import benchmark, components, fingerprint, lock, nvidia, provenance, runs
from ..core import check as checks
from ..core import manifest as manifests
from ..core import project as projects
from ..core.config import Config
from ..i18n import _
from ..utils import output

#: The six frozen audit scopes (§5.5), in report order.
SCOPES: tuple[str, ...] = (
    "project",
    "dependencies",
    "environment",
    "files",
    "runs",
    "reproducibility",
)

# severity -> (symbol, rich style); mirrors the §24 report glyphs.
_SEVERITY: dict[str, tuple[str, str]] = {
    "ok": ("✓", "green"),
    "warn": ("⚠", "yellow"),
    "error": ("✗", "red"),
}


@dataclass
class Finding:
    """One audited fact: a severity, a human message, an optional safe fix."""

    severity: str            # "ok" | "warn" | "error"
    message: str
    fix: str | None = None   # "dir:<project-relative/path>" — CAASI-owned (§26)

    def to_dict(self) -> dict:
        data = {"severity": self.severity, "message": self.message}
        if self.fix:
            data["fix"] = self.fix
        return data


# -- scopes -------------------------------------------------------------------


def _project(root: Path, config: Config) -> list[Finding]:
    path = root / manifests.MANIFEST_FILE
    if not path.is_file():
        return [Finding("error", _("audit.project.no_manifest"))]
    data = projects.load_project_meta(root)
    if not data:  # exists but empty/unparseable — cannot account for it
        return [Finding("error", _("audit.project.invalid_manifest"))]

    findings: list[Finding] = []
    if data.get("schema") != manifests.SCHEMA:
        findings.append(
            Finding("error", _("audit.project.bad_schema", schema=data.get("schema")))
        )
    else:
        findings.append(Finding("ok", _("audit.project.valid_manifest")))
    if not data.get("name"):
        findings.append(Finding("error", _("audit.project.no_name")))

    git = provenance.git_info(root)
    if git.get("available"):
        findings.append(
            Finding("warn", _("audit.project.dirty_tree"))
            if git.get("dirty")
            else Finding("ok", _("audit.project.clean_tree"))
        )
    return findings


def _dependencies(root: Path, config: Config) -> list[Finding]:
    # Reuse the Check Contract's detector so "is it there?" has one owner.
    items = checks.ProjectRequirementsChecker().run(
        checks.CheckContext(config=config, project_root=root)
    )
    if not items:
        return [Finding("ok", _("audit.dependencies.none"))]

    findings: list[Finding] = []
    for item in items:
        if item.compatibility == "compatible":
            findings.append(
                Finding(
                    "ok",
                    _("audit.dependencies.present", name=item.name, detected=item.detected or ""),
                )
            )
        elif item.compatibility == "untested":
            findings.append(
                Finding(
                    "warn",
                    _("audit.dependencies.warn", name=item.name, note=item.note or _("audit.dependencies.unverified")),
                )
            )
        else:  # missing / incompatible
            findings.append(Finding("error", _("audit.dependencies.missing", name=item.name)))
    return findings


def _environment(root: Path, config: Config) -> list[Finding]:
    findings: list[Finding] = []
    document = fingerprint.load(root)
    if document is None:
        findings.append(Finding("warn", _("audit.environment.no_fingerprint")))
    else:
        findings.append(Finding("ok", _("audit.environment.fingerprint")))

    if nvidia.available():
        findings.append(Finding("ok", _("audit.environment.gpu")))
    else:
        findings.append(Finding("warn", _("audit.environment.no_gpu")))

    cuda = checks.detect(config, "cuda")
    if cuda:
        findings.append(Finding("ok", _("audit.environment.cuda", version=cuda)))
    else:
        findings.append(Finding("warn", _("audit.environment.no_cuda")))

    if document is not None:
        recorded = ((document.get("environment") or {}).get("python") or {}).get("version")
        current = platform.python_version()
        if recorded and str(recorded) != current:
            findings.append(
                Finding("warn", _("audit.environment.python_drift", recorded=recorded, current=current))
            )
    return findings


def _files(root: Path, config: Config) -> list[Finding]:
    manifest = manifests.read(root)
    findings: list[Finding] = []

    missing: list[str] = [sub for sub in components.BASE_DIRS if not (root / sub).is_dir()]
    for key in manifest.registered():
        missing.extend(sub for sub in components.dirs_for(key) if not (root / sub).is_dir())
    if missing:
        # Missing CAASI directories are the one deterministic, CAASI-owned fix (§26).
        findings.extend(
            Finding("warn", _("audit.files.missing_dir", dir=sub), fix=f"dir:{sub}")
            for sub in missing
        )
    else:
        findings.append(Finding("ok", _("audit.files.dirs_present")))

    problems = 0
    for kind in projects.COMPONENT_KINDS:
        for entry in projects.list_definitions(root, kind):
            data = entry["data"]
            if not data or data.get("kind") != kind:
                problems += 1
                findings.append(
                    Finding(
                        "warn",
                        _("audit.files.bad_definition", file=f"{projects.KIND_DIRS[kind]}/{entry['name']}.yaml"),
                    )
                )
    if problems == 0:
        findings.append(Finding("ok", _("audit.files.definitions_ok")))
    return findings


def _runs(root: Path, config: Config) -> list[Finding]:
    base = runs.runs_dir(config)
    records = runs.list_runs(config)
    orphaned = sorted(
        path.name
        for path in base.iterdir()
        if path.is_dir() and not (path / "manifest.yaml").is_file()
    )
    if not records and not orphaned:
        return [Finding("ok", _("audit.runs.none"))]

    findings: list[Finding] = []
    if records:
        findings.append(Finding("ok", _("audit.runs.count", count=len(records))))
        latest = records[0]
        if runs.log_path(latest, "stdout") or runs.log_path(latest, "stderr"):
            findings.append(Finding("ok", _("audit.runs.logs")))
        else:
            findings.append(Finding("warn", _("audit.runs.no_logs")))

        stdout = runs.log_path(latest, "stdout")
        metrics: dict[str, float] = {}
        if stdout is not None:
            try:
                metrics = benchmark.parse_metrics(stdout.read_text(encoding="utf-8"))
            except OSError:
                metrics = {}
        findings.append(
            Finding("ok", _("audit.runs.metrics"))
            if metrics
            else Finding("warn", _("audit.runs.no_metrics"))
        )

    # Run directories without a manifest are stale CAASI runtime records (§26).
    findings.extend(Finding("warn", _("audit.runs.orphaned", name=name)) for name in orphaned)
    return findings


def _reproducibility(root: Path, config: Config) -> list[Finding]:
    findings: list[Finding] = []

    git = provenance.git_info(root)
    if git.get("available") and git.get("head"):
        findings.append(Finding("ok", _("audit.repro.git_commit")))
    elif git.get("available"):
        findings.append(Finding("warn", _("audit.repro.no_git_repo")))
    else:
        findings.append(Finding("warn", _("audit.repro.no_git")))

    findings.append(
        Finding("ok", _("audit.repro.fingerprint"))
        if fingerprint.load(root) is not None
        else Finding("warn", _("audit.repro.no_fingerprint"))
    )
    findings.append(
        Finding("ok", _("audit.repro.lock"))
        if lock.read(root) is not None
        else Finding("warn", _("audit.repro.no_lock"))
    )

    records = runs.list_runs(config)
    if records and records[0].directory is not None:
        run_dir = records[0].directory
        missing = [name for name in provenance.BUNDLE_FILES if not (run_dir / name).is_file()]
        findings.append(
            Finding("warn", _("audit.repro.incomplete_bundle", missing=", ".join(missing)))
            if missing
            else Finding("ok", _("audit.repro.bundle_complete"))
        )
    return findings


_SCOPE_FUNCS: dict[str, Callable[[Path, Config], list[Finding]]] = {
    "project": _project,
    "dependencies": _dependencies,
    "environment": _environment,
    "files": _files,
    "runs": _runs,
    "reproducibility": _reproducibility,
}


# -- safe fixes (§26) ---------------------------------------------------------


def _apply_fixes(root: Path, findings: list[Finding]) -> list[str]:
    """Apply CAASI-owned safe fixes in place; return what was fixed.

    Only ``dir:`` fixes are honoured — creating a missing CAASI directory. This
    never rewrites a manifest, deletes a record, kills a process or touches a
    user file; those stay report-only so an audit can never destroy evidence.
    """
    fixed: list[str] = []
    for finding in findings:
        if not finding.fix or not finding.fix.startswith("dir:"):
            continue
        relative = finding.fix[len("dir:") :]
        try:
            (root / relative).mkdir(parents=True, exist_ok=True)
        except OSError:
            continue
        fixed.append(relative)
        finding.severity = "ok"
        finding.message = _("audit.fix.created_dir", dir=relative)
        finding.fix = None
    return fixed


# -- command ------------------------------------------------------------------


def audit_command(
    scope: Optional[str] = typer.Argument(None, help=_("audit.arg.scope")),
    fix: bool = typer.Option(False, "--fix", help=_("audit.flag.fix")),
    json_output: bool = typer.Option(False, "--json", help=_("flag.json")),
) -> None:
    config = state.cfg()
    root = projects.find_project_root()
    if root is None:
        output.fail(_("audit.no_project"))
        raise typer.Exit(1)  # unreachable

    if scope is None:
        selected = list(SCOPES)
    elif scope in _SCOPE_FUNCS:
        selected = [scope]
    else:
        output.fail(_("audit.unknown_scope", scope=scope, valid=", ".join(SCOPES)))
        raise typer.Exit(1)  # unreachable

    groups = [(name, _SCOPE_FUNCS[name](root, config)) for name in selected]

    # §7.3: `audit.fix` is absent by default; the flag or the config key opts in.
    do_fix = fix or bool(config.get("audit.fix", False))
    fixed: list[str] = []
    if do_fix:
        for _name, findings in groups:
            fixed.extend(_apply_fixes(root, findings))

    warnings = sum(1 for _, fs in groups for f in fs if f.severity == "warn")
    errors = sum(1 for _, fs in groups for f in fs if f.severity == "error")
    result = "error" if errors else ("warning" if warnings else "ok")

    if output.wants_json(json_output):
        output.echo_json(
            {
                "scope": scope or "all",
                "result": result,
                "warnings": warnings,
                "errors": errors,
                "fixed": fixed,
                "groups": [
                    {"scope": name, "findings": [f.to_dict() for f in fs]}
                    for name, fs in groups
                ],
            }
        )
        raise typer.Exit(1 if errors else 0)

    output.echo(f"[bold]{_('audit.title')}[/bold]")
    for name, findings in groups:
        output.echo(f"\n[bold]{_(f'audit.scope.{name}')}[/bold]")
        for finding in findings:
            symbol, style = _SEVERITY[finding.severity]
            output.echo(f"  [{style}]{symbol}[/{style}] {finding.message}")
    if fixed:
        output.echo(_("audit.fix.summary", count=len(fixed)))
    output.echo(_("audit.result.line", warnings=warnings, errors=errors))
    raise typer.Exit(1 if errors else 0)
