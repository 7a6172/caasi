"""``caasi.lock``: resolved environment evidence (§56-57, §7.2).

``caasi.yaml`` says what a project *requires*; ``caasi.lock`` records what was
*resolved* on this machine when ``caasi env lock`` ran — evidence for audit
and reproduction discussions, never a freeze or a promise::

    schema: 1
    project: {name: warehouse-navigation, version: 0.1.0}
    required: {isaac_sim: {version: ">=5.0"}}
    resolved: {isaac_sim: 6.0.1, ros2: jazzy, python: 3.12.3, ...}
    verified: [...]
    collected_at: "2026-09-09T12:00:00+00:00"
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from . import check
from . import manifest as manifests
from .config import Config

LOCK_FILE = "caasi.lock"
SCHEMA = 1

#: Resolved even without a requires entry — the reproduction baseline (§7.2).
BASELINE: tuple[str, ...] = ("isaac_sim", "isaac_lab", "ros2", "python", "gcc", "cmake")


def resolve(config: Config, root: Path, names: list[str] | None = None) -> dict[str, str]:
    """Detect versions for *names* + BASELINE + the manifest's requires keys."""
    manifest = manifests.read(root)
    wanted = list(names or [])
    wanted.extend(BASELINE)
    wanted.extend(sorted(manifest.requires))
    resolved: dict[str, str] = {}
    for name in dict.fromkeys(wanted):
        detected = check.detect(config, name)
        if detected is not None:
            resolved[name] = detected
    return resolved


def build_document(root: Path, resolved: dict[str, str]) -> dict[str, Any]:
    manifest = manifests.read(root)
    return {
        "schema": SCHEMA,
        "project": {"name": manifest.name, "version": manifest.version},
        "required": dict(manifest.requires),
        "resolved": dict(resolved),
        "verified": list(manifest.tested),
        "collected_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }


def write(root: Path, resolved: dict[str, str]) -> Path:
    """Write ``<root>/caasi.lock``; returns its path."""
    document = build_document(root, resolved)
    path = root / LOCK_FILE
    path.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")
    return path


def read(root: Path) -> dict[str, Any] | None:
    """Load ``caasi.lock``, or None when absent/malformed."""
    try:
        data = yaml.safe_load((root / LOCK_FILE).read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        return None
    return data if isinstance(data, dict) else None
