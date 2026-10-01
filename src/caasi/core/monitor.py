"""Layer 7 monitoring: machine + run resource sampler (§4.6, §20-21).

One semantic operation — sample the resources the machine exposes (CPU, RAM,
GPU, VRAM, top processes) and, when a run is watched, its runtime and
throughput. The CLI process never imports the monitored stack: everything is
read from /proc, nvidia-smi and the run directory. Values that cannot be
measured are honestly reported as ``None`` (rendered "?"), never faked.
"""

from __future__ import annotations

import datetime as _dt
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

from ..utils import sysinfo
from . import benchmark, nvidia, runs
from .config import Config

# States a watched run can never leave again — `live` stops following there.
ACTIVE_STATES = (runs.RUNNING, runs.PAUSED)


@dataclass(frozen=True)
class Sample:
    """One resource observation. ``None`` fields mean "not measurable here"."""

    cpu: Optional[float] = None  # %
    ram_used: Optional[float] = None  # GiB
    ram_total: Optional[float] = None  # GiB
    gpu: Optional[float] = None  # % (busiest GPU)
    vram_used: Optional[float] = None  # GiB (summed over GPUs)
    vram_total: Optional[float] = None  # GiB (summed over GPUs)
    processes: list[sysinfo.ProcessInfo] = field(default_factory=list)
    runtime_s: Optional[float] = None
    steps_per_s: Optional[float] = None

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "cpu": self.cpu,
            "ram_used": self.ram_used,
            "ram_total": self.ram_total,
            "gpu": self.gpu,
            "vram_used": self.vram_used,
            "vram_total": self.vram_total,
            "processes": [
                {"pid": p.pid, "rss_kb": p.rss_kb, "command": p.command}
                for p in self.processes
            ],
            "runtime_s": self.runtime_s,
        }
        if self.steps_per_s is not None:  # §4.6: omitted when absent
            data["steps_per_s"] = self.steps_per_s
        return data


def _cpu_jiffies() -> Optional[tuple[int, int]]:
    """(busy, total) jiffies from the aggregate ``cpu`` line of /proc/stat."""
    try:
        line = Path("/proc/stat").read_text(encoding="utf-8").split("\n", 1)[0]
    except OSError:
        return None
    parts = line.split()
    if not parts or parts[0] != "cpu":
        return None
    values = [int(part) for part in parts[1:] if part.isdigit()]
    if len(values) < 4:
        return None
    idle = values[3] + (values[4] if len(values) > 4 else 0)  # idle + iowait
    total = sum(values)
    return total - idle, total


def cpu_percent(window: float = 0.25) -> Optional[float]:
    """Machine-wide CPU utilisation (%) measured across a *window*-second delta."""
    first = _cpu_jiffies()
    if first is None:
        return None
    time.sleep(window)
    second = _cpu_jiffies()
    if second is None:
        return None
    busy = second[0] - first[0]
    total = second[1] - first[1]
    if total <= 0:
        return None
    return round(busy * 100.0 / total, 1)


def _memory_gib() -> tuple[Optional[float], Optional[float]]:
    info = sysinfo.read_meminfo()
    total = info.get("MemTotal")
    if total is None:
        return None, None
    available = info.get("MemAvailable", info.get("MemFree", 0))
    used = max(total - available, 0)
    return round(used / 1024 / 1024, 1), round(total / 1024 / 1024, 1)


def _gpu_snapshot() -> tuple[Optional[float], Optional[float], Optional[float]]:
    """(gpu %, VRAM used GiB, VRAM total GiB), or Nones without nvidia-smi."""
    try:
        gpus = nvidia.query(list(nvidia.STATUS_FIELDS))
    except nvidia.NvidiaSmiError:
        return None, None, None
    utils = [g["utilization.gpu"] for g in gpus if isinstance(g.get("utilization.gpu"), (int, float))]
    used = [g["memory.used"] for g in gpus if isinstance(g.get("memory.used"), (int, float))]
    total = [g["memory.total"] for g in gpus if isinstance(g.get("memory.total"), (int, float))]
    return (
        max(utils) if utils else None,
        round(sum(used) / 1024.0, 1) if used else None,
        round(sum(total) / 1024.0, 1) if total else None,
    )


def _parse_created(record: runs.RunRecord) -> Optional[_dt.datetime]:
    try:
        created = _dt.datetime.fromisoformat(record.created)
    except ValueError:
        return None
    return created.astimezone()  # naive timestamps are local; runs writes aware ones


def _mtime(path: Path) -> Optional[_dt.datetime]:
    try:
        return _dt.datetime.fromtimestamp(path.stat().st_mtime).astimezone()
    except OSError:
        return None


def runtime_seconds(record: Optional[runs.RunRecord]) -> Optional[float]:
    """Wall-clock seconds since the run was created, frozen once it ends."""
    if record is None:
        return None
    start = _parse_created(record)
    if start is None:
        return None
    end: Optional[_dt.datetime] = None
    if record.directory is not None:
        status = runs.effective_status(record)
        if status in (runs.TERMINAL_OK, runs.TERMINAL_FAIL):
            end = _mtime(record.directory / "exit_code")
        elif status == runs.STOPPED:
            end = _mtime(record.directory / "manifest.yaml")
    seconds = ((end or _dt.datetime.now().astimezone()) - start).total_seconds()
    return round(max(seconds, 0.0), 1)


def steps_per_s(record: Optional[runs.RunRecord]) -> Optional[float]:
    """Throughput parsed from the run's stdout.log (§4.6); None when absent."""
    if record is None:
        return None
    path = runs.log_path(record, "stdout")
    if path is None:
        return None
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    metrics = benchmark.parse_metrics(text)
    for key in ("steps_per_sec", "simulation_fps"):
        if key in metrics:
            return metrics[key]
    return None


def sample(
    record: Optional[runs.RunRecord],
    config: Config,
    *,
    window: float = 0.25,
) -> Sample:
    """One observation of the machine plus (optionally) the watched run.

    *record* may be None: the machine half stays measurable without a run
    (the honest replacement for the dropped root ``status``).
    """
    ram_used, ram_total = _memory_gib()
    gpu, vram_used, vram_total = _gpu_snapshot()
    return Sample(
        cpu=cpu_percent(window),
        ram_used=ram_used,
        ram_total=ram_total,
        gpu=gpu,
        vram_used=vram_used,
        vram_total=vram_total,
        processes=sysinfo.top_processes(limit=5) or [],
        runtime_s=runtime_seconds(record),
        steps_per_s=steps_per_s(record),
    )


def live(
    record: Optional[runs.RunRecord],
    config: Config,
    interval: float,
    render: Callable[[Sample], Any],
) -> None:
    """Sample → *render(sample)* loop (the ``gpu monitor`` pattern, §4.6).

    Returns when the watched run leaves the active states; a machine-only
    watch (record None) runs until ``KeyboardInterrupt``, which propagates
    to the caller.
    """
    while True:
        render(sample(record, config))
        if record is not None and runs.effective_status(record) not in ACTIVE_STATES:
            return
        time.sleep(interval)
