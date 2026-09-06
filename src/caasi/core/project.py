"""Caasi projects: layout, creation, and robot/scene/task definitions.

A project is a directory containing ``caasi.yaml``::

    project/
    ├── caasi.yaml
    ├── robots/
    ├── scenes/
    ├── tasks/
    ├── experiments/
    ├── datasets/
    └── runs/

Robot, scene and task definitions are YAML files inside ``robots/``,
``scenes/`` and ``tasks/`` respectively. Everything is inspectable without
starting a simulation.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

PROJECT_FILE = "caasi.yaml"
COMPONENT_KINDS = ("robot", "scene", "task")
KIND_DIRS = {"robot": "robots", "scene": "scenes", "task": "tasks"}
PROJECT_DIRS = ("robots", "scenes", "tasks", "experiments", "datasets", "runs")

_NAME_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]*\Z")

TEMPLATES: dict[str, dict[str, Any]] = {
    "robot": {
        "kind": "robot",
        "name": "",
        "description": "",
        "urdf": "",
        "usd": "",
        "dof": 0,
        "sensors": [],
        "tasks": [],
    },
    "scene": {
        "kind": "scene",
        "name": "",
        "description": "",
        "usd": "",
    },
    "task": {
        "kind": "task",
        "name": "",
        "description": "",
    },
}


class ProjectError(ValueError):
    """Raised for invalid project operations."""


def valid_name(name: str) -> bool:
    return bool(_NAME_RE.match(name))


def find_project_root(start: Path | None = None) -> Path | None:
    """Walk up from *start* (default cwd) looking for ``caasi.yaml``."""
    current = (start or Path.cwd()).resolve()
    for candidate in (current, *current.parents):
        if (candidate / PROJECT_FILE).is_file():
            return candidate
    return None


def load_project_meta(root: Path) -> dict[str, Any]:
    path = root / PROJECT_FILE
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        return {}
    return data if isinstance(data, dict) else {}


def create_project(path: Path, name: str | None = None, force: bool = False) -> Path:
    """Create the project scaffold. Raises ProjectError when unsafe."""
    root = path.expanduser().resolve()
    project_file = root / PROJECT_FILE
    if project_file.is_file() and not force:
        raise ProjectError(f"'{project_file}' already exists (use --force to overwrite)")
    if root.is_file():
        raise ProjectError(f"'{root}' is a file")

    root.mkdir(parents=True, exist_ok=True)
    for sub in PROJECT_DIRS:
        (root / sub).mkdir(exist_ok=True)

    meta = {
        "kind": "project",
        "name": name or root.name,
        "version": 1,
    }
    project_file.write_text(
        yaml.safe_dump(meta, sort_keys=False), encoding="utf-8"
    )
    return root


def definitions_dir(root: Path, kind: str) -> Path:
    return root / KIND_DIRS[kind]


def _definition_path(root: Path, kind: str, name: str) -> Path:
    return definitions_dir(root, kind) / f"{name}.yaml"


def load_definition(root: Path, kind: str, name: str) -> dict[str, Any] | None:
    path = _definition_path(root, kind, name)
    if not path.is_file():
        return None
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        return {}
    return data if isinstance(data, dict) else {}


def list_definitions(root: Path, kind: str) -> list[dict[str, Any]]:
    """All definitions of *kind*, sorted by name: [{name, path, data}]."""
    directory = definitions_dir(root, kind)
    if not directory.is_dir():
        return []
    entries = []
    for path in sorted(directory.glob("*.yaml")):
        data = load_definition(root, kind, path.stem) or {}
        entries.append({"name": path.stem, "path": path, "data": data})
    return entries


def save_definition(
    root: Path, kind: str, name: str, description: str = "", overwrite: bool = False
) -> Path:
    """Write a fresh definition from the template. Raises ProjectError."""
    if not valid_name(name):
        raise ProjectError(
            f"invalid name '{name}' (use letters, digits, '-' and '_')"
        )
    path = _definition_path(root, kind, name)
    if path.is_file() and not overwrite:
        raise ProjectError(f"'{path}' already exists")
    data = dict(TEMPLATES[kind])
    data["name"] = name
    if description:
        data["description"] = description
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    return path


def validate_project(root: Path) -> list[str]:
    """Return a list of human-readable issues (empty when the project is valid)."""
    issues: list[str] = []
    project_file = root / PROJECT_FILE
    if not project_file.is_file():
        return [f"missing {PROJECT_FILE}"]
    try:
        data = yaml.safe_load(project_file.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        return [f"{PROJECT_FILE}: invalid YAML ({exc})"]
    if not isinstance(data, dict):
        return [f"{PROJECT_FILE}: must be a mapping"]
    if not data.get("name"):
        issues.append(f"{PROJECT_FILE}: 'name' is missing")

    for sub in PROJECT_DIRS:
        if not (root / sub).is_dir():
            issues.append(f"missing directory '{sub}/'")

    for kind in COMPONENT_KINDS:
        for entry in list_definitions(root, kind):
            label = f"{KIND_DIRS[kind]}/{entry['name']}.yaml"
            if not entry["data"]:
                issues.append(f"{label}: empty or invalid YAML")
                continue
            if entry["data"].get("kind") != kind:
                issues.append(f"{label}: kind is '{entry['data'].get('kind')}', expected '{kind}'")
    return issues
