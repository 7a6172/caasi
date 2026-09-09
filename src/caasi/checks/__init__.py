"""Doctor check engine.

Checks are grouped into sections. Each check module registers callables that
receive a :class:`CheckContext` and return :class:`CheckResult` objects. All
external probes are subprocess/metadata based — the CLI never imports heavy
robotics libraries.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import TYPE_CHECKING, Any, Callable, Literal

if TYPE_CHECKING:  # pragma: no cover
    from ..core.config import Config

Status = Literal["ok", "warn", "fail", "skip"]


@dataclass(frozen=True)
class CheckResult:
    section: str
    name: str
    status: Status
    detail: str = ""
    hint: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class CheckContext:
    config: "Config"


CheckFn = Callable[[CheckContext], list[CheckResult]]

# Ordered section keys; titles are resolved through i18n at render time.
SECTION_KEYS: list[str] = [
    "system",
    "hardware",
    "nvidia",
    "graphics",
    "python",
    "isaac",
    "ros",
    "robotics",
    "accelerated",
    "physics",
    "assets",
    "data",
    "platform",
    "ml",
    "vision",
    "simulators",
    "containers",
    "storage",
]

_REGISTRY: dict[str, list[CheckFn]] = {}


def register(section: str) -> Callable[[CheckFn], CheckFn]:
    def decorator(fn: CheckFn) -> CheckFn:
        _REGISTRY.setdefault(section, []).append(fn)
        return fn

    return decorator


def run_checks(
    sections: list[str] | None = None, config: "Config | None" = None
) -> list[CheckResult]:
    import_all_check_modules()
    from ..state import cfg as state_cfg

    ctx = CheckContext(config=config or state_cfg())
    results: list[CheckResult] = []
    for key in sections or SECTION_KEYS:
        for fn in _REGISTRY.get(key, []):
            results.extend(fn(ctx))
    return results


def import_all_check_modules() -> None:
    from . import (  # noqa: F401
        accelerated,
        containers,
        data,
        graphics,
        hardware,
        isaac,
        ml,
        nvidia,
        physics,
        platform,
        python_env,
        robotics,
        ros,
        simulators,
        storage,
        system,
        usd,
        vision,
    )
