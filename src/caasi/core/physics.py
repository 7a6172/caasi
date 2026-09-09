"""Physics engine selection (``plan3.md`` §27-28).

The physics "interface" is deliberately thin: it is a launcher choice and an
environment variable, nothing more. Caasi implements no physics — it picks the
engine the catalog resolves and hands the experiment to the right launcher:
PhysX through Isaac Sim's ``python.sh``, Newton through the Newton launcher
when one exists (``isaac-sim.newton.sh``). A new engine or a renamed launcher
is a catalog/config edit, not a code change.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import TYPE_CHECKING

from ..i18n import _
from . import adapters, catalog

if TYPE_CHECKING:  # pragma: no cover
    from .config import Config

DOMAIN = "physics"

#: Environment variable exported to every physics run.
ENGINE_ENV = "CAASI_PHYSICS_ENGINE"

#: Engine used when neither ``--engine`` nor ``physics.default`` says otherwise.
DEFAULT_ENGINE = "physx"


class PhysicsError(RuntimeError):
    """Raised when an engine cannot be resolved or applied."""


def engines(config: "Config | None" = None) -> tuple[catalog.Resolved, ...]:
    """Every physics engine of the catalog, resolved in order."""
    return catalog.resolve_domain(DOMAIN, config)


def engine_keys(config: "Config | None" = None) -> list[str]:
    spec = catalog.domain(DOMAIN, config)
    return [cap.key for cap in spec.capabilities] if spec else []


def default_engine(config: "Config | None" = None) -> str:
    value = config.get("physics.default") if config is not None else None
    return str(value or DEFAULT_ENGINE)


def pick_engine(
    config: "Config | None" = None, requested: str | None = None
) -> catalog.Resolved:
    """The engine to run: ``--engine`` → ``physics.default`` → physx.

    The engine must be detected on this machine; anything else is an honest
    failure naming the config key that would point at it.
    """
    key = str(requested or default_engine(config)).lower()
    known = engine_keys(config)
    if key not in known:
        raise PhysicsError(_("physics.unknown_engine", engine=key, known=", ".join(known)))
    item = catalog.resolve_capability(DOMAIN, key, config)
    if item is None or not item.found:
        cap = item.capability if item is not None else catalog.capability(DOMAIN, key, config)
        targets = catalog.targets(cap) if cap is not None else key
        field = catalog.override_field(cap) if cap is not None else "packages"
        raise PhysicsError(
            _("adapters.missing", domain=DOMAIN, cap=key, targets=targets)
            + " "
            + _("adapters.override_hint", domain=DOMAIN, cap=key, field=field)
        )
    return item


def launcher_for(
    item: catalog.Resolved, config: "Config | None" = None
) -> str | None:
    """The engine's own launcher script, or None to keep the experiment's.

    Two sources, in order: ``physics.engines.<key>.launcher`` from the config,
    and a launcher the catalog resolved through ``paths`` (Isaac Sim ships
    ``isaac-sim.newton.sh`` next to ``python.sh``).
    """
    configured = (
        config.get(f"physics.engines.{item.capability.key}.launcher")
        if config is not None
        else None
    )
    if configured:
        candidate = Path(str(configured)).expanduser()
        if not candidate.is_absolute():
            root = catalog.tool_root(config, "isaacsim")
            if root is not None:
                candidate = root / candidate
        if candidate.is_file():
            return str(candidate)
    if item.how == "path" and item.value and item.value.endswith(".sh"):
        return item.value
    return None


def apply_engine(
    item: catalog.Resolved,
    command: list[str],
    env: dict[str, str],
    config: "Config | None" = None,
) -> tuple[list[str], dict[str, str]]:
    """(command, env) with ``CAASI_PHYSICS_ENGINE`` set and the launcher swapped."""
    env = {**env, ENGINE_ENV: item.capability.key}
    launcher = launcher_for(item, config)
    if launcher and command:
        command = [launcher, *[str(part) for part in command[1:]]]
    return command, env


def python_for(config: "Config | None" = None) -> str:
    """Interpreter for python-side tools (``plan3.md`` §29).

    Isaac Sim's ``python.sh`` when a tool is registered, else this process'
    own Python. Warp and friends ship inside the Isaac Sim install, so its
    interpreter is the one that can see them.
    """
    adapter = adapters.adapter_for(DOMAIN)
    launcher = getattr(adapter, "launcher", None)
    return (launcher(config) if callable(launcher) else None) or sys.executable
