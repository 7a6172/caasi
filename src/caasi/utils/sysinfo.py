"""Linux system information readers (/proc based, no external dependencies)."""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from pathlib import Path


def read_meminfo() -> dict[str, int]:
    """Return /proc/meminfo values in KiB keyed by field name."""
    info: dict[str, int] = {}
    try:
        text = Path("/proc/meminfo").read_text(encoding="utf-8")
    except OSError:
        return info
    for line in text.splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[1].isdigit():
            info[parts[0].rstrip(":")] = int(parts[1])
    return info


def cpu_model() -> str | None:
    try:
        text = Path("/proc/cpuinfo").read_text(encoding="utf-8")
    except OSError:
        return None
    for line in text.splitlines():
        if line.lower().startswith("model name"):
            _, _, value = line.partition(":")
            value = value.strip()
            return value or None
    return None


def load_average() -> tuple[float, float, float] | None:
    try:
        return os.getloadavg()
    except (OSError, AttributeError):
        return None


def disk_usage(path: str | Path):
    """shutil.disk_usage result or None if the path cannot be queried."""
    try:
        return shutil.disk_usage(str(path))
    except OSError:
        return None


def existing_ancestor(path: Path) -> Path:
    """Walk up until an existing directory is found (for disk usage queries)."""
    current = path.expanduser()
    while not current.exists() and current.parent != current:
        current = current.parent
    return current


def os_pretty_name() -> str | None:
    try:
        text = Path("/etc/os-release").read_text(encoding="utf-8")
    except OSError:
        return None
    for line in text.splitlines():
        if line.startswith("PRETTY_NAME="):
            return line.split("=", 1)[1].strip().strip('"')
    return None


def human_bytes(size_bytes: float) -> str:
    """Format a byte count as a human readable string."""
    value = float(size_bytes)
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if abs(value) < 1024.0 or unit == "TiB":
            if unit == "B":
                return f"{int(value)} {unit}"
            return f"{value:.1f} {unit}"
        value /= 1024.0
    return f"{value:.1f} TiB"


@dataclass(frozen=True)
class ProcessInfo:
    pid: int
    rss_kb: int
    command: str


def top_processes(limit: int = 10) -> list[ProcessInfo] | None:
    """Scan /proc for the processes using the most memory.

    Returns None when /proc is not readable (non-Linux).
    """
    procs: list[ProcessInfo] = []
    try:
        entries = list(Path("/proc").iterdir())
    except OSError:
        return None
    for entry in entries:
        if not entry.name.isdigit():
            continue
        try:
            status = (entry / "status").read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        name = ""
        rss_kb = 0
        for line in status.splitlines():
            if line.startswith("Name:"):
                name = line.split(":", 1)[1].strip()
            elif line.startswith("VmRSS:"):
                parts = line.split()
                if len(parts) >= 2 and parts[1].isdigit():
                    rss_kb = int(parts[1])
        if name:
            procs.append(ProcessInfo(int(entry.name), rss_kb, name))
    procs.sort(key=lambda p: p.rss_kb, reverse=True)
    return procs[:limit]
