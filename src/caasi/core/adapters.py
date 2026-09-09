"""Adapter layer for catalog-driven groups (``plan3.md`` §53).

An adapter turns a catalog :class:`~caasi.core.catalog.Domain` into the four
things a Caasi group needs: detection, a ``--json`` status payload, a
delegating command line, and doctor results. Exactly two concrete adapters
exist — one for ROS-launchable domains, one for script/tool-launchable ones —
and they cover every catalog domain. There is deliberately no plugin system:
the catalog *is* the extension point.

Adapters never import the ecosystem they describe; they build command lines
for tools that already exist.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

from ..i18n import _
from . import catalog, ros, rosenv

if TYPE_CHECKING:  # pragma: no cover
    from ..checks import CheckResult
    from .config import Config

#: Launcher script inside a tool root, per registry name.
TOOL_SCRIPTS = {
    "isaacsim": "python.sh",
    "isaaclab": "isaaclab.sh",
    "groot": "python.sh",
}

#: Domain kinds each adapter handles.
ROS_KINDS = ("ros",)
SIM_KINDS = ("sim", "lab", "python", "mixed")

#: Doctor section a domain reports into.
SECTION_FOR_DOMAIN = {
    "isaacros": "accelerated",
    "perception": "accelerated",
    "slam": "accelerated",
    "mapping": "accelerated",
    "motion": "accelerated",
    "nitros": "accelerated",
    "physics": "physics",
    "warp": "physics",
    "groot": "platform",
    "cosmos": "platform",
    "teleop": "platform",
    "usd": "assets",
    "data": "data",
    "sdg": "data",
}


class AdapterError(RuntimeError):
    """Raised when a command cannot be built (missing tool / capability)."""


@runtime_checkable
class Adapter(Protocol):
    domain: str

    def detect(self, config: "Config | None") -> list[catalog.Resolved]: ...

    def status(self, config: "Config | None") -> dict[str, Any]: ...

    def command(
        self, config: "Config | None", cap_key: str, extra: list[str]
    ) -> tuple[list[str], dict[str, str]]: ...

    def check(self, config: "Config | None") -> "list[CheckResult]": ...

    def check_capability(
        self, item: catalog.Resolved, config: "Config | None"
    ) -> "CheckResult": ...


class _Base:
    """Shared behaviour for the two concrete adapters."""

    def __init__(self, domain: str) -> None:
        self.domain = domain

    # -- helpers ------------------------------------------------------
    def spec(self, config: "Config | None" = None) -> catalog.Domain:
        found = catalog.domain(self.domain, config)
        if found is None:
            raise AdapterError(_("adapters.unknown_domain", domain=self.domain))
        return found

    def detect(self, config: "Config | None" = None) -> list[catalog.Resolved]:
        return list(catalog.resolve_domain(self.domain, config))

    def section(self) -> str:
        return SECTION_FOR_DOMAIN.get(self.domain, self.domain)

    def status(self, config: "Config | None" = None) -> dict[str, Any]:
        spec = self.spec(config)
        resolved = self.detect(config)
        payload: dict[str, Any] = {
            "domain": spec.key,
            "kind": spec.kind,
            "tool": spec.tool,
            "root": str(catalog.tool_root(config, spec.tool))
            if catalog.tool_root(config, spec.tool)
            else None,
            "total": len(resolved),
            "installed": sum(1 for item in resolved if item.found),
            "capabilities": [item.to_dict() for item in resolved],
        }
        payload.update(self.extra_status(config))
        return payload

    def extra_status(self, config: "Config | None" = None) -> dict[str, Any]:
        return {}

    def check(self, config: "Config | None" = None) -> "list[CheckResult]":
        guard = self.check_guard(config)
        if guard is not None:
            return [guard]
        return [self.check_capability(item, config) for item in self.detect(config)]

    def check_capability(
        self, item: catalog.Resolved, config: "Config | None" = None
    ) -> "CheckResult":
        """One doctor row for one resolved capability."""
        from ..checks import CheckResult

        section = self.section()
        cap = item.capability
        if item.found:
            return CheckResult(
                section,
                _(cap.label),
                "ok",
                item.value or "",
                _("adapters.found_via", how=item.how),
            )
        if cap.core:
            return CheckResult(
                section,
                _(cap.label),
                "fail",
                _("adapters.not_found", targets=catalog.targets(cap)),
                _(
                    "adapters.override_hint",
                    domain=self.domain,
                    cap=cap.key,
                    field=catalog.override_field(cap),
                ),
            )
        return CheckResult(
            section,
            _(cap.label),
            "skip",
            _("adapters.not_found", targets=catalog.targets(cap)),
        )

    def check_guard(self, config: "Config | None" = None) -> "CheckResult | None":
        """A single result that replaces the whole section (e.g. no ros2 CLI)."""
        return None


class RosAdapter(_Base):
    """Domains launched through ``ros2 launch``."""

    def extra_status(self, config: "Config | None" = None) -> dict[str, Any]:
        distro, root = ros.find_distro()
        return {
            "ros_distro": distro,
            "ros_root": str(root) if root else None,
            "ros_sourced": rosenv.is_sourced(),
        }

    def check_guard(self, config: "Config | None" = None) -> "CheckResult | None":
        from ..checks import CheckResult

        if ros.find_ros2_binary():
            return None
        return CheckResult(
            self.section(),
            _(self.spec(config).title),
            "skip",
            _("doctor.robotics.no_ros2"),
            _("doctor.robotics.no_ros2_hint"),
        )

    def command(
        self, config: "Config | None", cap_key: str, extra: list[str]
    ) -> tuple[list[str], dict[str, str]]:
        binary = ros.require_ros2()
        item = catalog.resolve_capability(self.domain, cap_key, config)
        if item is None:
            raise AdapterError(
                _("adapters.unknown_capability", domain=self.domain, cap=cap_key)
            )
        if not item.found:
            raise AdapterError(
                _("adapters.missing", domain=self.domain, cap=cap_key, targets=catalog.targets(item.capability))
            )
        if not item.launch:
            raise AdapterError(
                _("adapters.no_launch", domain=self.domain, cap=cap_key)
            )
        package, launch_file = item.launch
        argv = [binary, "launch", package, launch_file, *extra]
        env = {} if rosenv.is_sourced() else rosenv.sourced_env()
        return argv, env


class SimAdapter(_Base):
    """Domains launched through a tool interpreter or a resolved script."""

    def launcher(self, config: "Config | None" = None) -> str | None:
        spec = self.spec(config)
        root = catalog.tool_root(config, spec.tool)
        if spec.tool and config is not None:
            resolved = config.resolve_tool(spec.tool)
            if resolved is not None and resolved.python:
                return resolved.python
        if root is not None:
            script = root / TOOL_SCRIPTS.get(spec.tool or "", "")
            if spec.tool and script.is_file():
                return str(script)
        env_value = os.environ.get(catalog.TOOL_ENV.get(spec.tool or "", ""))
        if env_value:
            candidate = Path(env_value).expanduser() / TOOL_SCRIPTS.get(spec.tool or "", "")
            if candidate.is_file():
                return str(candidate)
        if spec.kind in ("python", "mixed"):
            return sys.executable
        return None

    def extra_status(self, config: "Config | None" = None) -> dict[str, Any]:
        return {"launcher": self.launcher(config)}

    def command(
        self, config: "Config | None", cap_key: str, extra: list[str]
    ) -> tuple[list[str], dict[str, str]]:
        item = catalog.resolve_capability(self.domain, cap_key, config)
        if item is None:
            raise AdapterError(
                _("adapters.unknown_capability", domain=self.domain, cap=cap_key)
            )
        if not item.found:
            raise AdapterError(
                _("adapters.missing", domain=self.domain, cap=cap_key, targets=catalog.targets(item.capability))
            )

        if item.how == "binary":
            return [str(item.value), *extra], {}

        launcher = self.launcher(config)
        if not launcher:
            raise AdapterError(_("adapters.no_launcher", domain=self.domain))
        if item.script is not None:
            return [launcher, str(item.script), *extra], {}
        raise AdapterError(_("adapters.no_script", domain=self.domain, cap=cap_key))


# -- registry -------------------------------------------------------------

_REGISTRY: dict[str, Adapter] = {}


def register(adapter: Adapter) -> Adapter:
    _REGISTRY[adapter.domain] = adapter
    return adapter


def get(domain_key: str) -> Adapter | None:
    return _REGISTRY.get(domain_key)


def adapters() -> tuple[Adapter, ...]:
    return tuple(_REGISTRY.values())


def clear_registry() -> None:
    """Drop registered adapters (used by the test-suite)."""
    _REGISTRY.clear()


def adapter_class_for(kind: str) -> type[_Base] | None:
    if kind in ROS_KINDS:
        return RosAdapter
    if kind in SIM_KINDS:
        return SimAdapter
    return None


def build_adapters(config: "Config | None" = None) -> tuple[Adapter, ...]:
    """Instantiate (and register) one adapter per catalog domain."""
    built: list[Adapter] = []
    for spec in catalog.domains(config):
        cls = adapter_class_for(spec.kind)
        if cls is None:
            continue
        built.append(register(cls(spec.key)))
    return tuple(built)


def adapter_for(domain_key: str, config: "Config | None" = None) -> Adapter:
    """Return the adapter for a domain, building it on first use."""
    existing = _REGISTRY.get(domain_key)
    if existing is not None:
        return existing
    spec = catalog.domain(domain_key, config)
    if spec is None:
        raise AdapterError(_("adapters.unknown_domain", domain=domain_key))
    cls = adapter_class_for(spec.kind)
    if cls is None:
        raise AdapterError(_("adapters.unsupported_kind", domain=domain_key, kind=spec.kind))
    return register(cls(domain_key))
