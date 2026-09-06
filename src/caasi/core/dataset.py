"""Dataset system: layout conventions, discovery, validation and indexing.

A dataset is a directory containing ``metadata.json`` plus optional data
sub-directories::

    dataset/
    ├── metadata.json
    ├── episodes/
    ├── observations/
    ├── actions/
    ├── rewards/
    ├── poses/
    ├── images/
    ├── depth/
    └── lidar/

Generation itself happens inside a tracked run: `caasi dataset generate`
starts the experiment script with ``CAASI_DATASET_DIR`` pointing at the
dataset directory; the script writes the data while the CLI manages the
lifecycle.
"""

from __future__ import annotations

import csv
import datetime as _dt
import json
import re
from pathlib import Path
from typing import Any

from ..core.config import Config
from . import project

DATASET_META = "metadata.json"
KNOWN_DIRS = (
    "episodes",
    "observations",
    "actions",
    "rewards",
    "poses",
    "images",
    "depth",
    "lidar",
)
INDEX_FORMATS = ("jsonl", "csv")
_INDEX_FILES = ("index.jsonl", "index.csv")


class DatasetError(ValueError):
    """Raised for invalid dataset operations."""


def _slug(name: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", name.strip()).strip("-").lower()
    return slug or "dataset"


def datasets_base(config: Config) -> Path:
    """Project ``datasets/`` when inside a project, else the global path."""
    root = project.find_project_root()
    if root is not None:
        base = root / "datasets"
    else:
        base = config.expanded_path_for("paths.datasets") or Path.home() / ".caasi" / "datasets"
    base.mkdir(parents=True, exist_ok=True)
    return base


def new_dataset_dir(base: Path, name: str) -> Path:
    return base / f"{_slug(name)}-{_dt.datetime.now():%Y%m%d-%H%M%S}"


def meta_path(path: Path) -> Path:
    return path / DATASET_META


def read_metadata(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(meta_path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def write_metadata(path: Path, data: dict[str, Any]) -> Path:
    target = meta_path(path)
    target.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
    return target


def list_datasets(base: Path) -> list[Path]:
    """Datasets under *base*, newest first."""
    if not base.is_dir():
        return []
    found = [
        child
        for child in sorted(base.iterdir(), reverse=True)
        if child.is_dir() and meta_path(child).is_file()
    ]
    return found


def find_dataset(config: Config, query: str) -> Path | None:
    """Resolve *query*: a directory path, an exact name, a unique prefix or 'latest'."""
    query = query.strip()
    candidate = Path(query).expanduser()
    if candidate.is_dir() and meta_path(candidate).is_file():
        return candidate.resolve()

    base = datasets_base(config)
    datasets = list_datasets(base)
    if query in ("latest", "last", "newest"):
        return datasets[0] if datasets else None
    matches = [p for p in datasets if p.name == query or p.name.startswith(query)]
    return matches[0] if len(matches) == 1 else None


def _count_files(path: Path) -> int:
    if not path.is_dir():
        return 0
    return sum(1 for child in path.rglob("*") if child.is_file())


def scan_dataset(path: Path) -> dict[str, Any]:
    """File counts and sizes for the dataset sub-directories."""
    dirs: dict[str, int] = {}
    for sub in KNOWN_DIRS:
        count = _count_files(path / sub)
        if count:
            dirs[sub] = count
    files = [child for child in path.rglob("*") if child.is_file()]
    size = sum(child.stat().st_size for child in files)
    return {"files": len(files), "size": size, "dirs": dirs}


def validate_dataset(path: Path) -> list[str]:
    """Human-readable issues (empty when the dataset is valid)."""
    issues: list[str] = []
    meta_file = meta_path(path)
    if not meta_file.is_file():
        return [f"missing {DATASET_META}"]
    try:
        data = json.loads(meta_file.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return [f"{DATASET_META}: invalid JSON ({exc})"]
    if not isinstance(data, dict):
        return [f"{DATASET_META}: must be a JSON object"]
    if not data.get("name"):
        issues.append(f"{DATASET_META}: 'name' is missing")

    expected = data.get("episodes")
    episodes = path / "episodes"
    if isinstance(expected, int) and episodes.is_dir():
        count = _count_files(episodes)
        if count != expected:
            issues.append(
                f"metadata declares {expected} episode(s) but episodes/ contains {count}"
            )
    return issues


def index_dataset(path: Path) -> list[dict[str, Any]]:
    """All data files (relative path + size), excluding metadata/index files."""
    entries = []
    for child in sorted(path.rglob("*")):
        if not child.is_file():
            continue
        if child.name in (DATASET_META, *_INDEX_FILES):
            continue
        entries.append({"path": str(child.relative_to(path)), "size": child.stat().st_size})
    return entries


def write_index(path: Path, fmt: str, output: Path | None = None) -> tuple[Path, int]:
    """Write a portable index (jsonl/csv) of the dataset files.

    Returns (index path, entry count). Raises DatasetError for unknown formats.
    """
    if fmt not in INDEX_FORMATS:
        raise DatasetError(
            f"unknown index format '{fmt}' (expected one of {', '.join(INDEX_FORMATS)})"
        )
    entries = index_dataset(path)
    target = Path(output) if output else path / f"index.{fmt}"
    if fmt == "jsonl":
        target.write_text(
            "".join(json.dumps(entry) + "\n" for entry in entries), encoding="utf-8"
        )
    else:
        with target.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            writer.writerow(["path", "size"])
            for entry in entries:
                writer.writerow([entry["path"], entry["size"]])
    return target, len(entries)
