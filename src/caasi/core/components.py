"""Project-structure knowledge as data (mirrors ``core/catalog.py``).

A *component* is an optional capability subtree of a project. ``project init``
creates only the :data:`BASE_DIRS`; ``project add <component>`` materialises the
component's own directories, registers it in the manifest and merges its
``requires`` stub. Organising by capability (``isaac.sim``, ``ros2``) rather than
by vendor keeps the tree stable across upstream renames.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class Component:
    key: str                      # "isaac_lab"  (manifest form)
    cli: str                      # "isaac.lab"  (dotted form for `project add`)
    dirs: tuple[str, ...]         # project-relative directories created on add
    requires: dict[str, Any] = field(default_factory=dict)  # merged into caasi.yaml `requires:`
    base: bool = False            # created by `project init`


#: Directories every project gets from ``project init``.
BASE_DIRS: tuple[str, ...] = (
    "robots",
    "scenes",
    "tasks",
    "experiments",
    "datasets",
    "runs",
    "artifacts",
    "logs",
    ".caasi",
)


COMPONENTS: dict[str, Component] = {
    "isaac_sim": Component(
        key="isaac_sim",
        cli="isaac.sim",
        dirs=("isaac/sim/scenes", "isaac/sim/configs", "isaac/sim/extensions"),
        requires={"isaac_sim": {"version": ">=5.0"}},
    ),
    "isaac_lab": Component(
        key="isaac_lab",
        cli="isaac.lab",
        dirs=("isaac/lab/tasks", "isaac/lab/environments", "isaac/lab/configs"),
        requires={"isaac_lab": {"version": ">=2.0"}},
    ),
    "ros2": Component(
        key="ros2",
        cli="ros2",
        dirs=("ros/launch", "ros/config", "ros/params"),
        requires={"ros2": {}},
    ),
    "nav2": Component(
        key="nav2",
        cli="nav2",
        dirs=("nav/maps", "nav/params", "nav/launch"),
        requires={"nav2": {}},
    ),
    "moveit": Component(
        key="moveit",
        cli="moveit",
        dirs=("moveit/config", "moveit/launch"),
        requires={"moveit": {}},
    ),
    # `robot/` holds asset *descriptions* (URDF/meshes/USD) and deliberately
    # coexists with the base `robots/` definitions directory.
    "robot": Component(
        key="robot",
        cli="robot",
        dirs=("robot/urdf", "robot/meshes", "robot/usd"),
    ),
    "navigation": Component(
        key="navigation",
        cli="navigation",
        dirs=("navigation/configs", "navigation/launch"),
    ),
    "manipulation": Component(
        key="manipulation",
        cli="manipulation",
        dirs=("manipulation/configs", "manipulation/launch"),
    ),
}


def normalize(name: str) -> str | None:
    """Map ``isaac.lab`` ↔ ``isaac_lab`` to a known component key (else None)."""
    if not name:
        return None
    key = name.strip().replace(".", "_").replace("-", "_").lower()
    return key if key in COMPONENTS else None


def get(name: str) -> Component | None:
    key = normalize(name)
    return COMPONENTS.get(key) if key else None


def all() -> list[Component]:  # noqa: A001 - mirrors the plan's API name
    return list(COMPONENTS.values())


def dirs_for(name: str) -> tuple[str, ...]:
    comp = get(name)
    return comp.dirs if comp else ()


def requires_for(name: str) -> dict[str, Any]:
    comp = get(name)
    return dict(comp.requires) if comp else {}
