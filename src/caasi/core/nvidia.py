"""nvidia-smi query helpers shared by `caasi gpu` and diagnostics.

The CLI shells out to nvidia-smi (the existing NVIDIA mechanism) instead of
binding GPU libraries itself.
"""

from __future__ import annotations

import re

from ..utils import shell

# Fields for `caasi gpu status`.
STATUS_FIELDS = [
    "index",
    "name",
    "driver_version",
    "memory.total",
    "memory.used",
    "memory.free",
    "utilization.gpu",
    "temperature.gpu",
    "power.draw",
]

# Extra fields for `caasi gpu info`.
INFO_FIELDS = [
    "index",
    "name",
    "uuid",
    "serial",
    "pci.bus_id",
    "compute_cap",
    "ecc.mode.current",
    "driver_version",
]


class NvidiaSmiError(RuntimeError):
    """Raised when nvidia-smi is missing or fails."""


def available() -> bool:
    return shell.which("nvidia-smi") is not None


def _to_float(value: str | None) -> float | None:
    if value is None:
        return None
    value = value.strip()
    if not value or value == "[N/A]" or value.lower() == "not supported":
        return None
    try:
        return float(value)
    except ValueError:
        return None


def query(fields: list[str], timeout: float = 10.0) -> list[dict[str, str | float | None]]:
    """Query GPUs via nvidia-smi CSV output. Raises NvidiaSmiError on failure."""
    if not available():
        raise NvidiaSmiError("nvidia-smi not found on PATH")
    result = shell.run_cmd(
        [
            "nvidia-smi",
            f"--query-gpu={','.join(fields)}",
            "--format=csv,noheader,nounits",
        ],
        timeout=timeout,
    )
    if not result.ok:
        detail = (result.stderr or result.stdout).strip() or "unknown error"
        raise NvidiaSmiError(detail)

    gpus: list[dict[str, str | float | None]] = []
    for line in result.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        cells = [cell.strip() for cell in line.split(",")]
        row: dict[str, str | float | None] = {}
        string_fields = ("name", "uuid", "serial", "pci.bus_id", "driver_version", "ecc.mode.current")
        for field, cell in zip(fields, cells):
            row[field] = cell if field in string_fields else _to_float(cell)
        gpus.append(row)
    if not gpus:
        raise NvidiaSmiError("nvidia-smi returned no GPUs")
    return gpus


def cuda_version(timeout: float = 10.0) -> str | None:
    """Driver-reported CUDA version parsed from plain `nvidia-smi` output."""
    if not available():
        return None
    result = shell.run_cmd(["nvidia-smi"], timeout=timeout)
    if not result.ok:
        return None
    match = re.search(r"CUDA Version:\s+([\d.]+)", result.stdout)
    return match.group(1) if match else None


def compute_apps(timeout: float = 10.0) -> list[dict[str, str | float | None]]:
    """Per-process GPU memory users."""
    if not available():
        return []
    fields = ["gpu_uuid", "pid", "process_name", "used_memory"]
    result = shell.run_cmd(
        [
            "nvidia-smi",
            f"--query-compute-apps={','.join(fields)}",
            "--format=csv,noheader,nounits",
        ],
        timeout=timeout,
    )
    if not result.ok:
        return []
    apps: list[dict[str, str | float | None]] = []
    for line in result.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        cells = [cell.strip() for cell in line.split(",")]
        if len(cells) < len(fields):
            continue
        apps.append(
            {
                "gpu_uuid": cells[0],
                "pid": _to_float(cells[1]),
                "process_name": cells[2],
                "used_memory_mb": _to_float(cells[3]),
            }
        )
    return apps
