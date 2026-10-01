"""Environment fingerprints: storage, stable hashing and comparison (Layer 2).

A fingerprint records what the environment *was* — evidence, never a
reproduction promise (§57). Storage: ``<project>/.caasi/environment/`` inside a
project, else ``~/.caasi/environment/`` — one YAML per section plus
``fingerprint.json`` (schema, hash, collected_at, full environment).

``stable_hash`` canonicalises (sorted keys, scalars → strings) and **excludes
volatile fields** (timestamps, PIDs, load average, free memory) so the same
machine hashes identically across runs; the digest is sha256 over compact JSON.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from . import environment
from .config import Config

HASH_PREFIX = "caasi-env-sha256:"
SCHEMA = 1
FINGERPRINT_FILE = "fingerprint.json"
SUBDIR = Path(".caasi") / "environment"

#: Keys scrubbed before hashing/comparison — they differ run to run by nature.
VOLATILE_KEYS: frozenset[str] = frozenset(
    {
        "collected_at",
        "timestamp",
        "pid",
        "load_average",
        "memory_available_kib",
        "memory_free_kib",
        "processes",
        "uptime_s",
    }
)


@dataclass(frozen=True)
class Diff:
    """One meaningfully-different leaf between two environments (§60)."""

    component: str          # top-level section, e.g. "python"
    key: str                # dotted path inside the section, e.g. "version"
    left: Any
    right: Any

    def to_dict(self) -> dict[str, Any]:
        return {"component": self.component, "key": self.key, "left": self.left, "right": self.right}


def collect(config: Config, sections: tuple[str, ...] | None = None) -> dict[str, Any]:
    return environment.collect(config, sections=sections)


def environment_dir(root: Path) -> Path:
    return root / SUBDIR


def _canonical(value: Any) -> Any:
    """Scrub volatile keys and normalise scalars to strings (versions included)."""
    if isinstance(value, dict):
        return {
            k: _canonical(v)
            for k, v in sorted(value.items(), key=lambda item: str(item[0]))
            if str(k) not in VOLATILE_KEYS
        }
    if isinstance(value, (list, tuple)):
        return [_canonical(item) for item in value]
    if value is None or isinstance(value, str):
        return value
    return str(value)


def as_environment(doc: Any) -> dict[str, Any]:
    """Accept either a raw environment dict or a fingerprint document."""
    if isinstance(doc, dict) and isinstance(doc.get("environment"), dict):
        return doc["environment"]
    return doc if isinstance(doc, dict) else {}


def stable_hash(fp: Any) -> str:
    canonical = _canonical(as_environment(fp))
    payload = json.dumps(canonical, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return HASH_PREFIX + hashlib.sha256(payload.encode("utf-8")).hexdigest()


def write(root: Path, fp: dict[str, Any]) -> Path:
    """Persist per-section YAML files + ``fingerprint.json``; returns its path."""
    directory = environment_dir(root)
    directory.mkdir(parents=True, exist_ok=True)
    for section, data in fp.items():
        (directory / f"{section}.yaml").write_text(
            yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8"
        )
    document = {
        "schema": SCHEMA,
        "hash": stable_hash(fp),
        "collected_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "environment": fp,
    }
    path = directory / FINGERPRINT_FILE
    path.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def load(root: Path) -> dict[str, Any] | None:
    """Load a stored fingerprint document, or None when absent/unreadable."""
    path = environment_dir(root) / FINGERPRINT_FILE
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return document if isinstance(document, dict) else None


def _leaves(value: Any, prefix: str = "") -> dict[str, Any]:
    """Flatten a canonicalised section into dotted leaf paths."""
    leaves: dict[str, Any] = {}
    if isinstance(value, dict):
        for key, item in value.items():
            path = f"{prefix}.{key}" if prefix else str(key)
            leaves.update(_leaves(item, path))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            leaves.update(_leaves(item, f"{prefix}[{index}]"))
    else:
        leaves[prefix] = value
    return leaves


def compare(a: Any, b: Any) -> list[Diff]:
    """Meaningfully-different components between two environments (§60).

    Volatile fields are excluded, so only changes that matter for
    reproducibility (versions, paths, counts, availability) are reported.
    """
    left = _canonical(as_environment(a))
    right = _canonical(as_environment(b))
    diffs: list[Diff] = []
    for section in dict.fromkeys(list(left) + list(right)):
        if section not in left or section not in right:
            diffs.append(Diff(section, "", left.get(section), right.get(section)))
            continue
        left_leaves = _leaves(left[section])
        right_leaves = _leaves(right[section])
        for key in dict.fromkeys(list(left_leaves) + list(right_leaves)):
            l_value = left_leaves.get(key)
            r_value = right_leaves.get(key)
            if l_value != r_value:
                diffs.append(Diff(section, key, l_value, r_value))
    return diffs
