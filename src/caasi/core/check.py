"""The Check Contract: one compatibility semantics behind every `check` (§4.5).

CAASI commands may have several entry points (root ``check``, ``sim check``,
``container check``, ``control check``) but one underlying operation: answer
"can this work here?" with the same vocabulary.

The §16 ladder — how evidence maps onto compatibility, and compatibility
onto the report result::

    evidence                       compatibility    result
    -----------------------------  ---------------  ------------------
    tested & verified              compatible       ready (VERIFIED)
    requirement satisfied          compatible       ready
    no requirement / no version    untested         warning
    detected out of range          untested (*)     warning
    required thing not detected    missing          incompatible
    functional probe failed        incompatible     incompatible

(*) §57 evidence-not-guarantees: a version outside a required range yields a
warning with an explanatory note — CAASI does not assert incompatibility from
version ranges alone. ``incompatible`` is reserved for positively failed
functional probes (daemon down, malformed params, doctor "fail" statuses).

Exit policy (uniform): ``incompatible`` → exit 3, everything else → 0.
``check.strict`` (absent by default, §7.3) escalates warnings to incompatible
in the root orchestrator only.

``core/check.py`` (singular) is deliberately distinct from the doctor package
``caasi/checks/`` (plural), which stays the machine-wide probe registry that
:class:`SimChecker` delegates to.

Checkers return their :class:`CheckItem` list and :class:`CheckEngine` folds items into
:class:`CheckReport`s, so scope naming and ``check.strict`` have exactly one owner (the
§4.5 sketch has ``Checker.run`` return the report — same contract, one place to change).
"""

from __future__ import annotations

import platform
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal, Protocol, runtime_checkable

from ..checks.isaac import detect_isaac_lab, detect_isaac_sim
from ..i18n import _
from ..utils import pydist, shell
from . import fingerprint
from . import manifest as manifests
from . import nvidia, requirements
from . import ros as ros_core
from .config import Config

Compatibility = Literal["compatible", "untested", "missing", "incompatible"]
Result = Literal["ready", "warning", "incompatible"]

RESULT_ORDER: dict[str, int] = {"ready": 0, "warning": 1, "incompatible": 2}


@dataclass(frozen=True)
class CheckItem:
    """One checked fact: what was required, what was detected, the verdict."""

    name: str
    required: str | None
    detected: str | None
    compatibility: Compatibility
    note: str = ""
    verified: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class CheckReport:
    """A scope's items folded into one result (the uniform JSON contract)."""

    scope: str
    items: list[CheckItem]
    missing: list[str]
    warnings: list[str]
    result: Result

    def to_dict(self) -> dict[str, Any]:
        return {
            "scope": self.scope,
            "items": [item.to_dict() for item in self.items],
            "missing": list(self.missing),
            "warnings": list(self.warnings),
            "result": self.result,
        }


@dataclass
class CheckContext:
    """Everything a checker may consult; ``extra`` carries entry-point data."""

    config: Config
    project_root: Path | None = None
    run: Any | None = None
    strict: bool = False
    extra: dict[str, Any] = field(default_factory=dict)


class CheckError(ValueError):
    """Raised for unknown check scopes."""


def summarize(items: list[CheckItem], strict: bool = False) -> Result:
    if any(item.compatibility in ("missing", "incompatible") for item in items):
        return "incompatible"
    if any(item.compatibility == "untested" for item in items):
        return "incompatible" if strict else "warning"
    return "ready"


def build_report(scope: str, items: list[CheckItem], strict: bool = False) -> CheckReport:
    missing = [item.name for item in items if item.compatibility == "missing"]
    warnings = [
        item.name for item in items if item.compatibility in ("untested", "incompatible")
    ]
    return CheckReport(scope, list(items), missing, warnings, summarize(items, strict))


def worst(reports: list[CheckReport]) -> Result:
    result: Result = "ready"
    for report in reports:
        if RESULT_ORDER[report.result] > RESULT_ORDER[result]:
            result = report.result  # type: ignore[assignment]
    return result


@runtime_checkable
class Checker(Protocol):
    scope: str

    def relevant(self, ctx: CheckContext) -> bool: ...

    def run(self, ctx: CheckContext) -> list[CheckItem]: ...


# -- checkers -----------------------------------------------------------------


class EnvironmentChecker:
    """Fingerprint evidence: has this environment been recorded (§56)?"""

    scope = "environment"

    def relevant(self, ctx: CheckContext) -> bool:
        return True

    def run(self, ctx: CheckContext) -> list[CheckItem]:
        document = fingerprint.load(ctx.project_root or Path.home())
        if document is None:
            return [
                CheckItem("fingerprint", None, None, "untested", _("check.note.no_fingerprint"))
            ]
        detected = str(document.get("collected_at") or document.get("hash") or "")
        return [CheckItem("fingerprint", None, detected or None, "compatible")]


class ProjectRequirementsChecker:
    """``caasi.yaml`` requires/components versus detected versions (§4.4)."""

    scope = "project"

    def relevant(self, ctx: CheckContext) -> bool:
        return ctx.project_root is not None

    def run(self, ctx: CheckContext) -> list[CheckItem]:
        root = ctx.project_root
        if root is None:  # pragma: no cover - relevant() guarantees a root
            return []
        manifest = manifests.read(root)
        items: list[CheckItem] = []
        for name in sorted(manifest.requires):
            items.append(self._requirement_item(ctx, name, manifest.requires[name], manifest.tested))
        for component in sorted(manifest.registered()):
            if component in manifest.requires:
                continue
            detected = detect(ctx.config, component)
            items.append(
                CheckItem(component, None, detected, "untested", _("check.note.no_requirements"))
            )
        return items

    def _requirement_item(
        self, ctx: CheckContext, name: str, entry: Any, tested: list[Any]
    ) -> CheckItem:
        spec = _version_spec(entry)
        detected = detect(ctx.config, name)
        verified = _is_verified(tested, name, detected)
        if detected is None:
            return CheckItem(name, spec, None, "missing", _("check.note.not_detected"))
        if not spec:
            if verified:
                return CheckItem(name, None, detected, "compatible", _("check.note.verified"), True)
            return CheckItem(name, None, detected, "untested", _("check.note.no_version"))
        verdict = requirements.satisfies(detected, spec)
        if verdict is True:
            if verified:
                return CheckItem(name, spec, detected, "compatible", _("check.note.verified"), True)
            return CheckItem(name, spec, detected, "compatible")
        if verdict is False:
            return CheckItem(
                name,
                spec,
                detected,
                "untested",
                _("check.note.out_of_range", required=spec, detected=detected),
            )
        return CheckItem(
            name, spec, detected, "untested", _("check.note.unverifiable", required=spec)
        )


def _version_spec(entry: Any) -> str | None:
    """``">=5.0"`` or ``{version: ">=5.0"}`` → the specifier string (or None)."""
    if isinstance(entry, dict):
        value = entry.get("version")
        return str(value).strip() if value not in (None, "") else None
    if entry is None or str(entry).strip() == "":
        return None
    return str(entry).strip()


def _is_verified(tested: list[Any], name: str, detected: str | None) -> bool:
    """True when the manifest records this component as tested *and verified*."""
    for entry in tested:
        if not isinstance(entry, dict):
            continue
        component = entry.get("component", entry.get("name"))
        if str(component or "") != name or entry.get("status") != "verified":
            continue
        expected = entry.get("version")
        if expected is None or detected is None or str(expected) == str(detected):
            return True
    return False


class SimChecker:
    """Simulation readiness: delegates to doctor probe sections (`sim check`)."""

    scope = "sim"

    #: Doctor sections answering "can Isaac Sim run here?" (§5.3).
    SIM_SECTIONS: tuple[str, ...] = ("isaac", "nvidia", "hardware", "storage")

    _STATUS_COMPATIBILITY = {
        "ok": "compatible",
        "warn": "untested",
        "fail": "incompatible",
        "skip": "untested",
    }

    def relevant(self, ctx: CheckContext) -> bool:
        if ctx.project_root is None:
            return False
        registered = manifests.read(ctx.project_root).registered()
        return "isaac_sim" in registered or "isaac_lab" in registered

    def run(self, ctx: CheckContext) -> list[CheckItem]:
        # Late import so tests can monkeypatch `caasi.checks.run_checks`.
        from ..checks import run_checks

        results = run_checks(list(self.SIM_SECTIONS), ctx.config)
        items: list[CheckItem] = []
        for result in results:
            compatibility = self._STATUS_COMPATIBILITY.get(result.status, "untested")
            items.append(
                CheckItem(
                    result.name,
                    None,
                    result.detail or None,
                    compatibility,  # type: ignore[arg-type]
                    note=result.hint,
                )
            )
        return items


class ContainerChecker:
    """Container runtime facts (`container check`): tool, daemon, GPU runtime."""

    scope = "container"

    def relevant(self, ctx: CheckContext) -> bool:
        return bool(ctx.extra.get("containers"))

    def run(self, ctx: CheckContext) -> list[CheckItem]:
        from . import containers

        tool = containers.find_container_tool()
        if not tool:
            return [
                CheckItem("tool", None, None, "missing", _("container.no_tool")),
                CheckItem("daemon", None, None, "missing", _("container.daemon_fail")),
                CheckItem("nvidia-runtime", None, None, "missing", _("container.gpu_fail")),
            ]
        name = Path(tool).name
        items = [CheckItem("tool", None, name, "compatible")]
        daemon = containers.daemon_ok(tool)
        items.append(
            CheckItem(
                "daemon",
                None,
                name if daemon else None,
                "compatible" if daemon else "incompatible",
                _("container.daemon_ok") if daemon else _("container.daemon_fail"),
            )
        )
        if not daemon:
            items.append(CheckItem("nvidia-runtime", None, None, "missing", _("container.gpu_fail")))
            return items
        gpu = containers.nvidia_runtime(tool)
        items.append(
            CheckItem(
                "nvidia-runtime",
                None,
                name if gpu else None,
                "compatible" if gpu else "incompatible",
                _("container.gpu_ok") if gpu else _("container.gpu_fail"),
            )
        )
        return items


class ControlChecker:
    """Structural validation of ros2_control params (`control check`)."""

    scope = "control"

    def relevant(self, ctx: CheckContext) -> bool:
        return "params" in ctx.extra

    def run(self, ctx: CheckContext) -> list[CheckItem]:
        data = ctx.extra.get("params")
        if not isinstance(data, dict):
            return [CheckItem("params", None, None, "incompatible", _("control.issue.mapping"))]
        manager = data.get("controller_manager")
        params = manager.get("ros__parameters") if isinstance(manager, dict) else None
        if not isinstance(params, dict):
            return [
                CheckItem(
                    "controller_manager", None, None, "incompatible", _("control.issue.no_manager")
                )
            ]
        items: list[CheckItem] = []
        rate = params.get("update_rate")
        if rate is None:
            items.append(
                CheckItem(
                    "controller_manager", None, None, "incompatible", _("control.issue.no_rate")
                )
            )
        else:
            items.append(
                CheckItem("controller_manager", None, f"update_rate={rate}", "compatible")
            )
        for key, value in params.items():
            if not isinstance(value, dict):
                continue
            controller_type = value.get("type")
            if controller_type:
                items.append(CheckItem(str(key), None, str(controller_type), "compatible"))
            else:
                items.append(
                    CheckItem(
                        str(key), None, None, "incompatible", _("control.issue.no_type", controller=key)
                    )
                )
        return items


class RunChecker:
    """Pre-flight a stored run: can its command still execute here?"""

    scope = "run"

    def relevant(self, ctx: CheckContext) -> bool:
        return ctx.run is not None

    def run(self, ctx: CheckContext) -> list[CheckItem]:
        record = ctx.run
        items: list[CheckItem] = []
        command = [str(part) for part in (getattr(record, "command", None) or [])]
        if not command:
            items.append(CheckItem("command", None, None, "missing", _("check.note.no_command")))
        else:
            executable = command[0]
            path = Path(executable)
            found = (
                (executable if path.exists() else None)
                if path.is_absolute()
                else shell.which(executable)
            )
            if found:
                items.append(CheckItem("command", None, found, "compatible"))
            else:
                items.append(
                    CheckItem(
                        "command", None, executable, "missing", _("check.note.not_detected")
                    )
                )
        cwd = getattr(record, "cwd", None)
        if cwd:
            exists = Path(str(cwd)).expanduser().is_dir()
            items.append(
                CheckItem(
                    "cwd",
                    None,
                    str(cwd),
                    "compatible" if exists else "missing",
                    "" if exists else _("check.note.not_detected"),
                )
            )
        experiment = (getattr(record, "extra", None) or {}).get("experiment")
        if experiment:
            exists = Path(str(experiment)).expanduser().is_file()
            items.append(
                CheckItem(
                    "experiment",
                    None,
                    str(experiment),
                    "compatible" if exists else "missing",
                    "" if exists else _("check.note.not_detected"),
                )
            )
        return items


# -- detection ----------------------------------------------------------------


def _binary_version(binary: str) -> str | None:
    path = shell.which(binary)
    if not path:
        return None
    result = shell.run_cmd([path, "--version"])
    lines = (result.stdout or result.stderr).strip().splitlines()
    if not result.ok or not lines:
        return None
    parsed = requirements.parse_version(lines[0])
    return ".".join(str(part) for part in parsed) if parsed else None


def _isaac_version(config: Config, tool_name: str, detect_fn: Any) -> str | None:
    """Registered version (else version parsed from the detection detail)."""
    status, detail, _hint = detect_fn(config)
    if status != "ok":
        return None
    tool = config.resolve_tool(tool_name)
    if tool is not None and tool.version:
        return tool.version
    parsed = requirements.parse_version(detail)
    return ".".join(str(part) for part in parsed) if parsed else "installed"


def _prefix_str(prefix: Path | None) -> str | None:
    return str(prefix) if prefix else None


_DETECTORS: dict[str, Any] = {
    "isaac_sim": lambda config: _isaac_version(config, "isaacsim", detect_isaac_sim),
    "isaac_lab": lambda config: _isaac_version(config, "isaaclab", detect_isaac_lab),
    "ros2": lambda config: ros_core.find_distro()[0],
    "nav2": lambda config: _prefix_str(ros_core.pkg_prefix("nav2_bringup")),
    "moveit": lambda config: _prefix_str(ros_core.pkg_prefix("moveit_core")),
    "python": lambda config: platform.python_version(),
    "torch": lambda config: pydist.pip_version("torch"),
    "tensorrt": lambda config: pydist.pip_version("tensorrt"),
    "cuda": lambda config: nvidia.cuda_version(),
    "gcc": lambda config: _binary_version("gcc"),
    "g++": lambda config: _binary_version("g++"),
    "clang": lambda config: _binary_version("clang"),
    "cmake": lambda config: _binary_version("cmake"),
    "docker": lambda config: _binary_version("docker"),
    "git": lambda config: _binary_version("git"),
}


def detect(config: Config, name: str) -> str | None:
    """Best-effort detected version/presence of *name*. Never raises."""
    raw = str(name).strip()
    key = raw.replace("-", "_").replace(".", "_")
    detector = _DETECTORS.get(raw) or _DETECTORS.get(key)
    try:
        if detector is not None:
            value = detector(config)
            return str(value) if value is not None else None
        found = shell.which(raw) or shell.which(key)
        return "present" if found else None
    except Exception:  # noqa: BLE001 - detection failures degrade to None
        return None


# -- engine -------------------------------------------------------------------

DEFAULT_CHECKERS: tuple[type, ...] = (
    EnvironmentChecker,
    ProjectRequirementsChecker,
    SimChecker,
    ContainerChecker,
    ControlChecker,
    RunChecker,
)


class CheckEngine:
    """Runs checkers and folds their items into :class:`CheckReport`s."""

    def __init__(self, checkers: tuple[type, ...] | None = None):
        self.checkers: list[Checker] = [cls() for cls in (checkers or DEFAULT_CHECKERS)]

    def orchestrate(
        self, ctx: CheckContext, scopes: list[str] | None = None
    ) -> list[CheckReport]:
        """Every relevant checker (optionally filtered), ``check.strict`` applied."""
        reports: list[CheckReport] = []
        for checker in self.checkers:
            if scopes is not None and checker.scope not in scopes:
                continue
            if not checker.relevant(ctx):
                continue
            reports.append(build_report(checker.scope, checker.run(ctx), ctx.strict))
        return reports

    def one(self, scope: str, ctx: CheckContext) -> CheckReport:
        """Explicit entry point: run *scope* regardless of relevance."""
        for checker in self.checkers:
            if checker.scope == scope:
                return build_report(scope, checker.run(ctx))
        raise CheckError(f"unknown check scope '{scope}'")
