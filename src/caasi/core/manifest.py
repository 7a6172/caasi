"""Flat project manifest (``caasi.yaml``) read/write/migrate.

The manifest is a *flat* mapping keyed by an integer ``schema`` marker::

    schema: 1
    name: warehouse-navigation
    version: 0.1.0            # project version (string)
    components: { isaac_sim: true, ros2: true }
    requires: { ... }
    tested: [ ... ]

Manifest keys are deliberately disjoint from the *config* keys that
``core/config.py`` also reads out of ``caasi.yaml`` (``language``, ``layout``,
``tools``, ``catalog``, ...), so the same file serves both roles safely.

Legacy ``{kind, name, version: 1}`` files are bridged by :func:`migrate` to
``schema=1`` / ``version="0.0.0"``. **Reads never rewrite**; only ``project
init/add/remove`` persist changes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from . import components

SCHEMA = 1
MANIFEST_FILE = "caasi.yaml"

#: Manifest keys, in the order they are written.
FIELD_ORDER = ("schema", "name", "version", "components", "requires", "tested")


@dataclass
class Manifest:
    name: str = ""
    version: str = "0.0.0"
    components: dict[str, Any] = field(default_factory=dict)
    requires: dict[str, Any] = field(default_factory=dict)
    tested: list[Any] = field(default_factory=list)
    schema: int = SCHEMA

    def registered(self) -> list[str]:
        """Component keys whose manifest value is truthy."""
        return [k for k, v in self.components.items() if v]

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {"schema": self.schema, "name": self.name, "version": self.version}
        if self.components:
            data["components"] = dict(self.components)
        if self.requires:
            data["requires"] = dict(self.requires)
        if self.tested:
            data["tested"] = list(self.tested)
        return data


def migrate(data: dict[str, Any]) -> dict[str, Any]:
    """Bridge legacy ``{kind, name, version: 1}`` to the flat ``schema`` form."""
    data = dict(data or {})
    if "schema" in data:
        return data
    version = data.get("version")
    data["schema"] = SCHEMA
    data["version"] = version if isinstance(version, str) else "0.0.0"
    data.pop("kind", None)
    data.setdefault("components", {})
    return data


def _read_raw(root: Path) -> dict[str, Any]:
    path = root / MANIFEST_FILE
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        return {}
    return data if isinstance(data, dict) else {}


def read(root: Path) -> Manifest:
    data = migrate(_read_raw(root))
    components_field = data.get("components")
    requires = data.get("requires")
    tested = data.get("tested")
    schema = data.get("schema")
    return Manifest(
        name=str(data.get("name", "") or ""),
        version=str(data.get("version", "0.0.0") or "0.0.0"),
        components=dict(components_field) if isinstance(components_field, dict) else {},
        requires=dict(requires) if isinstance(requires, dict) else {},
        tested=list(tested) if isinstance(tested, list) else [],
        schema=int(schema) if isinstance(schema, int) else SCHEMA,
    )


def write(root: Path, manifest: Manifest) -> Path:
    path = root / MANIFEST_FILE
    data = manifest.to_dict()
    # Preserve any extra config-layer keys already present in the file.
    existing = _read_raw(root)
    merged = {k: v for k, v in existing.items() if k not in FIELD_ORDER and k != "kind"}
    merged.update(data)
    ordered = {k: merged[k] for k in FIELD_ORDER if k in merged}
    ordered.update({k: v for k, v in merged.items() if k not in FIELD_ORDER})
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(ordered, sort_keys=False), encoding="utf-8")
    return path


def add_component(root: Path, key: str) -> Manifest:
    manifest = read(root)
    manifest.components[key] = True
    stub = components.requires_for(key)
    for name, value in stub.items():
        existing = manifest.requires.get(name)
        if isinstance(existing, dict) and isinstance(value, dict):
            for field_name, field_value in value.items():
                existing.setdefault(field_name, field_value)
        else:
            manifest.requires.setdefault(name, value)
    write(root, manifest)
    return manifest


def remove_component(root: Path, key: str) -> Manifest:
    manifest = read(root)
    manifest.components.pop(key, None)
    write(root, manifest)
    return manifest
