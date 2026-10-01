"""Environment collection by delegation only (Layer 2, §12-14).

The CLI never imports the heavy stack: every section reuses an existing
detector (``utils/sysinfo``, ``core/nvidia``, ``core/ros``, ``checks/isaac``,
``utils/pydist``) or a plain ``--version`` subprocess probe. Each probe
degrades to an honest ``None``/empty value — collection never raises.
"""

from __future__ import annotations

import os
import platform
import sys
from typing import Any, Callable

from ..checks.isaac import detect_isaac_lab, detect_isaac_sim
from ..utils import pydist, shell, sysinfo
from . import nvidia
from . import ros as ros_core
from .config import Config

#: Canonical section order — also the ``.caasi/environment/*.yaml`` file names.
SECTION_ORDER: tuple[str, ...] = (
    "system",
    "hardware",
    "gpu",
    "drivers",
    "compilers",
    "python",
    "ros",
    "isaac",
    "docker",
    "git",
)

COMPILERS = ("gcc", "g++", "clang", "cmake")

#: Python distributions recorded for reproducibility (metadata only).
PYTHON_PACKAGES = {"torch": ("torch",), "tensorrt": ("tensorrt", "tensorrt_libs")}


def _version_probe(binary: str) -> str | None:
    """First line of ``<binary> --version``, or None when unavailable."""
    if shell.which(binary) is None:
        return None
    result = shell.run_cmd([binary, "--version"], timeout=10.0)
    if not result.ok:
        return None
    first = result.stdout.strip().splitlines()
    return first[0].strip() if first else None


def _system() -> dict[str, Any]:
    return {
        "os": sysinfo.os_pretty_name(),
        "kernel": platform.release(),
        "arch": platform.machine(),
        "hostname": platform.node(),
    }


def _hardware() -> dict[str, Any]:
    meminfo = sysinfo.read_meminfo()
    return {
        "cpu_model": sysinfo.cpu_model(),
        "cpu_count": os.cpu_count(),
        "memory_total_kib": meminfo.get("MemTotal"),
        # volatile: excluded from the stable hash by core/fingerprint
        "memory_available_kib": meminfo.get("MemAvailable"),
    }


def _nvidia_devices() -> list[dict[str, Any]]:
    if not nvidia.available():
        return []
    try:
        rows = nvidia.query(["name", "uuid", "memory.total", "driver_version"])
    except nvidia.NvidiaSmiError:
        return []
    return [
        {
            "name": row.get("name"),
            "uuid": row.get("uuid"),
            "memory_total_mib": row.get("memory.total"),
            "driver_version": row.get("driver_version"),
        }
        for row in rows
    ]


def _gpu() -> dict[str, Any]:
    return {"devices": _nvidia_devices()}


def _drivers() -> dict[str, Any]:
    devices = _nvidia_devices()
    driver = devices[0]["driver_version"] if devices else None
    return {"nvidia": driver, "cuda": nvidia.cuda_version()}


def _compilers() -> dict[str, Any]:
    return {name: _version_probe(name) for name in COMPILERS}


def _python() -> dict[str, Any]:
    return {
        "version": platform.python_version(),
        "implementation": platform.python_implementation(),
        "executable": sys.executable,
        "venv": sys.prefix != getattr(sys, "base_prefix", sys.prefix),
        "packages": {
            label: pydist.pip_version(*candidates)
            for label, candidates in PYTHON_PACKAGES.items()
        },
    }


def _ros() -> dict[str, Any]:
    distro, root = ros_core.find_distro()
    packages = len(ros_core.ros2_lines(["pkg", "list"])) if root is not None else None
    overlays = [p for p in os.environ.get("AMENT_PREFIX_PATH", "").split(":") if p]
    return {
        "distro": distro,
        "root": str(root) if root else None,
        "packages": packages,
        "rmw": os.environ.get("RMW_IMPLEMENTATION"),
        "domain_id": os.environ.get("ROS_DOMAIN_ID"),
        "overlays": overlays,
    }


def _isaac(config: Config) -> dict[str, Any]:
    sim_status, sim_detail, _ = detect_isaac_sim(config)
    lab_status, lab_detail, _ = detect_isaac_lab(config)
    return {
        "sim": {"status": sim_status, "detail": sim_detail},
        "lab": {"status": lab_status, "detail": lab_detail},
    }


def _docker() -> dict[str, Any]:
    installed = shell.which("docker") is not None
    return {"installed": installed, "version": _version_probe("docker") if installed else None}


def _git() -> dict[str, Any]:
    installed = shell.which("git") is not None
    return {"installed": installed, "version": _version_probe("git") if installed else None}


def collect(config: Config, sections: tuple[str, ...] | None = None) -> dict[str, Any]:
    """Collect environment sections (all by default).

    ``sections`` narrows the probe set — useful for tests and for callers that
    only need part of the picture. Unknown names are ignored.
    """
    probes: dict[str, Callable[[], dict[str, Any]]] = {
        "system": _system,
        "hardware": _hardware,
        "gpu": _gpu,
        "drivers": _drivers,
        "compilers": _compilers,
        "python": _python,
        "ros": _ros,
        "isaac": lambda: _isaac(config),
        "docker": _docker,
        "git": _git,
    }
    wanted = [name for name in SECTION_ORDER if sections is None or name in set(sections)]
    return {name: probes[name]() for name in wanted}
