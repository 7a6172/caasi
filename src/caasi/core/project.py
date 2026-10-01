"""Caasi projects: layout, creation, and robot/scene/task definitions.

A project is a directory containing ``caasi.yaml``. ``project init`` creates the
:data:`~caasi.core.components.BASE_DIRS`; ``project add <component>`` grows the
tree with capability subtrees (§5)::

    project/
    ├── caasi.yaml          # flat manifest (schema/name/version/components/…) + config layer
    ├── .caasi/             # internal: fingerprints, locks, provenance
    ├── robots/ scenes/ tasks/        # definition YAML (kind: robot|scene|task)
    ├── experiments/ datasets/ runs/ artifacts/ logs/
    ├── robot/urdf …        # `robot` component: asset *descriptions*
    └── isaac/sim …         # `isaac_sim` component subtree

Robot, scene and task definitions are YAML files inside ``robots/``, ``scenes/``
and ``tasks/`` respectively — note the singular ``robot/`` component subtree
holds asset files and deliberately coexists with the plural ``robots/``
definitions directory. Everything is inspectable without starting a simulation.
"""

from __future__ import annotations

import re
import shutil
from pathlib import Path
from typing import Any

import yaml

from . import components, manifest as manifests

PROJECT_FILE = manifests.MANIFEST_FILE
COMPONENT_KINDS = ("robot", "scene", "task")
KIND_DIRS = {"robot": "robots", "scene": "scenes", "task": "tasks"}

#: Base directories created by ``project init`` (re-exported from components).
PROJECT_DIRS: tuple[str, ...] = components.BASE_DIRS

#: Manifest keys that ``project validate`` understands (disjoint from config keys).
MANIFEST_KEYS: tuple[str, ...] = manifests.FIELD_ORDER


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
    """Raw ``caasi.yaml`` as a mapping, bridged through :func:`manifest.migrate`."""
    path = root / PROJECT_FILE
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        return {}
    if not isinstance(data, dict):
        return {}
    return manifests.migrate(data)


def read_manifest(root: Path) -> manifests.Manifest:
    return manifests.read(root)


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
        (root / sub).mkdir(parents=True, exist_ok=True)

    manifests.write(
        root,
        manifests.Manifest(name=name or root.name, version="0.0.0", schema=manifests.SCHEMA),
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
    """Component-aware validation. Returns human-readable issues (empty = valid)."""
    issues: list[str] = []
    project_file = root / PROJECT_FILE
    if not project_file.is_file():
        return [f"missing {PROJECT_FILE}"]
    try:
        raw = yaml.safe_load(project_file.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        return [f"{PROJECT_FILE}: invalid YAML ({exc})"]
    if not isinstance(raw, dict):
        return [f"{PROJECT_FILE}: must be a mapping"]

    data = manifests.migrate(raw)
    schema = data.get("schema")
    if not isinstance(schema, int):
        issues.append(f"{PROJECT_FILE}: 'schema' must be an integer (got {schema!r})")
    elif schema != manifests.SCHEMA:
        issues.append(
            f"{PROJECT_FILE}: unknown schema {schema} (this Caasi understands {manifests.SCHEMA})"
        )
    if not data.get("name"):
        issues.append(f"{PROJECT_FILE}: 'name' is missing")

    requires = data.get("requires")
    if requires is not None and not isinstance(requires, dict):
        issues.append(f"{PROJECT_FILE}: 'requires' must be a mapping")

    for sub in PROJECT_DIRS:
        if not (root / sub).is_dir():
            issues.append(f"missing directory '{sub}/'")

    manifest = manifests.read(root)
    for key in manifest.registered():
        for sub in components.dirs_for(key):
            if not (root / sub).is_dir():
                issues.append(f"component '{key}': missing directory '{sub}/'")

    for kind in COMPONENT_KINDS:
        for entry in list_definitions(root, kind):
            label = f"{KIND_DIRS[kind]}/{entry['name']}.yaml"
            if not entry["data"]:
                issues.append(f"{label}: empty or invalid YAML")
                continue
            if entry["data"].get("kind") != kind:
                issues.append(f"{label}: kind is '{entry['data'].get('kind')}', expected '{kind}'")
    return issues


# -- component tree management -------------------------------------------

#: ``project add-file <domain> <kind>`` → project-relative base directory.
FILE_DOMAINS: dict[str, str] = {
    "robot": "robot",
    "isaac.sim": "isaac/sim",
    "isaac.lab": "isaac/lab",
    "ros": "ros",
    "ros2": "ros",
    "nav": "nav",
    "nav2": "nav",
    "moveit": "moveit",
}

#: ``project add-file`` kind → leaf directory name.
FILE_KIND_DIRS: dict[str, str] = {
    "urdf": "urdf",
    "xacro": "urdf",
    "usd": "usd",
    "mesh": "meshes",
    "scene": "scenes",
    "config": "config",
    "launch": "launch",
    "param": "params",
    "params": "params",
    "map": "maps",
}


def registered_components(root: Path) -> list[str]:
    return manifests.read(root).registered()


def add_component(root: Path, key: str) -> manifests.Manifest:
    """Register *key* in the manifest and create its directories."""
    manifest = manifests.add_component(root, key)
    for sub in components.dirs_for(key):
        (root / sub).mkdir(parents=True, exist_ok=True)
    return manifest


def remove_component(
    root: Path, key: str, purge: bool = False
) -> tuple[manifests.Manifest, dict[str, list[str]]]:
    """Unregister *key*; remove now-empty dirs (``--purge`` deletes non-empty).

    Returns the updated manifest and ``{"removed": [...], "kept": [...]}`` where
    ``kept`` lists directories left behind because they were non-empty and not
    purged.
    """
    removed: list[str] = []
    kept: list[str] = []
    for sub in components.dirs_for(key):
        directory = root / sub
        if not directory.is_dir():
            continue
        if purge:
            shutil.rmtree(directory, ignore_errors=True)
            removed.append(sub)
            continue
        try:
            directory.rmdir()
            removed.append(sub)
        except OSError:
            kept.append(sub)
    manifest = manifests.remove_component(root, key)
    return manifest, {"removed": removed, "kept": kept}


def placement_dir(root: Path, domain: str, kind: str) -> Path:
    """Deterministic destination directory for ``project add-file``."""
    normalized = domain.strip().lower().replace("-", "_").replace(".", "_")
    dotted = normalized.replace("_", ".")
    base = (
        FILE_DOMAINS.get(dotted)
        or FILE_DOMAINS.get(normalized)
        or normalized.replace("_", "/")
    )
    leaf = FILE_KIND_DIRS.get(kind.strip().lower(), kind.strip().lower())
    return root / base / leaf


def place_file(root: Path, domain: str, kind: str, source: Path) -> Path:
    """Copy *source* into its deterministic location; returns the new path."""
    source = source.expanduser()
    if not source.is_file():
        raise ProjectError(f"'{source}' is not a file")
    dest_dir = placement_dir(root, domain, kind)
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / source.name
    shutil.copy2(source, dest)
    return dest

