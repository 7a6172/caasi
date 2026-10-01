"""Run provenance bundle (§4.7, Layer 6).

Written into the run directory when a tracked run starts (``caasi run start``
and every launcher that delegates to it). The bundle answers "what exactly
produced this run?" long after the process is gone:

- ``manifest.yaml``      — the run manifest, enriched with project identity
                           and the CAASI version (run identity = ``record.run_id``)
- ``environment.yaml``   — every environment section except hardware
- ``hardware.yaml``      — CPU/memory snapshot at launch
- ``dependencies.yaml``  — required/resolved/verified versions (evidence, not
                           a freeze — same shape as ``caasi.lock``)
- ``configuration.yaml`` — effective CAASI config + experiment config, secrets redacted
- ``git.json``           — HEAD/branch/dirty/remotes, or ``{"available": false}``
- ``processes.json``     — top processes by memory at launch

Provenance degrades honestly (§14.13): no git → ``{"available": false}``;
no project → project keys omitted; a file that cannot be written is skipped
rather than failing the run that already started.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from .. import __version__
from ..utils import shell, sysinfo
from . import environment, lock
from . import manifest as manifests
from . import project as projects
from .config import Config
from .runs import RunRecord

#: Key-name markers for secret values; matched case-insensitively as substrings.
SECRET_MARKERS = (
    "password",
    "passwd",
    "secret",
    "token",
    "credential",
    "api_key",
    "apikey",
    "private_key",
    "identity",
)

REDACTED = "***redacted***"

#: Files the bundle writes, in order (manifest.yaml is enriched in place).
BUNDLE_FILES = (
    "manifest.yaml",
    "environment.yaml",
    "hardware.yaml",
    "dependencies.yaml",
    "configuration.yaml",
    "git.json",
    "processes.json",
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def is_secret_key(key: Any) -> bool:
    lowered = str(key).lower()
    return any(marker in lowered for marker in SECRET_MARKERS)


def redact_secrets(data: Any) -> Any:
    """Recursively replace values whose key looks secret with ``REDACTED``."""
    if isinstance(data, dict):
        return {
            key: REDACTED if is_secret_key(key) else redact_secrets(value)
            for key, value in data.items()
        }
    if isinstance(data, list):
        return [redact_secrets(item) for item in data]
    return data


def git_info(root: Path) -> dict[str, Any]:
    """rev-parse HEAD/branch/dirty/remotes for *root*; honest when unavailable."""
    if shell.which("git") is None:
        return {"available": False}

    def _git(*args: str) -> shell.ShellResult:
        return shell.run_cmd(["git", "-C", str(root), *args], timeout=15.0)

    head = _git("rev-parse", "HEAD")
    if not head.ok:  # not a repository (or git refused) — say so, don't guess
        return {"available": False}
    branch = _git("rev-parse", "--abbrev-ref", "HEAD")
    status = _git("status", "--porcelain")
    remotes = _git("remote", "-v")
    remote_map: dict[str, str] = {}
    for line in remotes.stdout.splitlines():
        parts = line.split()
        if len(parts) >= 2 and line.rstrip().endswith("(fetch)"):
            remote_map[parts[0]] = parts[1]
    return {
        "available": True,
        "head": head.stdout.strip() or None,
        "branch": branch.stdout.strip() if branch.ok else None,
        "dirty": bool(status.stdout.strip()) if status.ok else None,
        "remotes": remote_map,
    }


def process_snapshot(limit: int = 10) -> dict[str, Any]:
    """Top processes by memory at launch; ``{"available": false}`` without /proc."""
    processes = sysinfo.top_processes(limit)
    if processes is None:
        return {"available": False}
    return {
        "available": True,
        "processes": [
            {"pid": p.pid, "rss_kb": p.rss_kb, "command": p.command} for p in processes
        ],
    }


def _enriched_manifest(run_dir: Path, project_root: Path | None) -> dict[str, Any]:
    try:
        data = yaml.safe_load((run_dir / "manifest.yaml").read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        data = {}
    if not isinstance(data, dict):
        data = {}
    data["caasi"] = {"version": __version__}
    if project_root is not None:
        manifest = manifests.read(project_root)
        data["project"] = {"name": manifest.name, "version": manifest.version}
    return data


def _dependencies(config: Config, root: Path, project_root: Path | None) -> dict[str, Any]:
    manifest = manifests.read(root)
    document: dict[str, Any] = {"schema": lock.SCHEMA}
    if project_root is not None:
        document["project"] = {"name": manifest.name, "version": manifest.version}
    document.update(
        {
            "required": dict(manifest.requires),
            "resolved": lock.resolve(config, root),
            "verified": list(manifest.tested),
            "collected_at": _now(),
        }
    )
    return document


def _configuration(config: Config, record: RunRecord) -> dict[str, Any]:
    document: dict[str, Any] = {"caasi": redact_secrets(config.data)}
    source = (record.extra or {}).get("experiment")
    if source:
        try:
            raw = yaml.safe_load(Path(str(source)).read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError):
            raw = None
        if isinstance(raw, dict):
            document["experiment"] = redact_secrets(raw)
    return document


def write_bundle(config: Config, record: RunRecord) -> list[Path]:
    """Write the §4.7 provenance bundle into the run directory.

    Returns the files actually written; an unwritable file is skipped (the run
    already started — provenance must not take it down).
    """
    run_dir = record.directory
    if run_dir is None or not run_dir.is_dir():
        return []
    cwd = Path(record.cwd) if record.cwd else Path.cwd()
    project_root = projects.find_project_root(cwd)
    root = project_root or cwd
    collected_at = _now()
    written: list[Path] = []

    def _dump(path: Path, text: str) -> None:
        try:
            path.write_text(text, encoding="utf-8")
            written.append(path)
        except OSError:
            pass  # degrade honestly: skipped file, run keeps going

    def _dump_yaml(name: str, data: dict[str, Any]) -> None:
        _dump(run_dir / name, yaml.safe_dump(data, sort_keys=False))

    def _dump_json(name: str, data: dict[str, Any]) -> None:
        _dump(run_dir / name, json.dumps(data, indent=2, default=str) + "\n")

    _dump_yaml("manifest.yaml", _enriched_manifest(run_dir, project_root))

    sections = tuple(name for name in environment.SECTION_ORDER if name != "hardware")
    _dump_yaml("environment.yaml", {"collected_at": collected_at, **environment.collect(config, sections)})
    hardware = environment.collect(config, ("hardware",)).get("hardware", {})
    _dump_yaml("hardware.yaml", {"collected_at": collected_at, **hardware})

    _dump_yaml("dependencies.yaml", _dependencies(config, root, project_root))
    _dump_yaml("configuration.yaml", _configuration(config, record))
    _dump_json("git.json", git_info(root))
    _dump_json("processes.json", process_snapshot())
    return written
