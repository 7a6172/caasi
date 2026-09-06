"""Sensor discovery: cameras, depth-camera SDKs, LiDAR and simulated sensors.

Discovery is metadata-only: devices come from ``/dev`` + sysfs, SDKs from
pip metadata. The CLI never imports vendor SDKs; `caasi sensor test` only
reports whether each source is available.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from ..checks.isaac import detect_isaac_sim
from ..core.config import Config
from ..utils import pydist

DEV_ROOT = Path("/dev")
V4L_SYS_ROOT = Path("/sys/class/video4linux")
ZED_PATHS: tuple[Path, ...] = (Path("/usr/local/zed"),)


@dataclass
class SensorInfo:
    name: str
    kind: str
    detected: bool
    detail: str = ""
    devices: list[str] = field(default_factory=list)
    hint: str = ""


def list_cameras(
    dev_root: Path | None = None, sys_root: Path | None = None
) -> list[tuple[str, str]]:
    """Return [(device path, sysfs name)] for video4linux devices."""
    dev_root = dev_root or DEV_ROOT
    sys_root = sys_root or V4L_SYS_ROOT
    if not dev_root.is_dir():
        return []
    devices = []
    for entry in sorted(dev_root.glob("video*")):
        name = ""
        try:
            name = (sys_root / entry.name / "name").read_text(encoding="utf-8").strip()
        except OSError:
            pass
        devices.append((str(entry), name))
    return devices


def list_serial_devices(dev_root: Path | None = None) -> list[str]:
    """Serial devices commonly used by LiDARs (ttyUSB*/ttyACM*)."""
    dev_root = dev_root or DEV_ROOT
    if not dev_root.is_dir():
        return []
    return sorted(
        str(path)
        for pattern in ("ttyUSB*", "ttyACM*")
        for path in dev_root.glob(pattern)
    )


def detect_sensors(
    config: Config,
    dev_root: Path | None = None,
    sys_root: Path | None = None,
    zed_paths: tuple[Path, ...] | None = None,
) -> list[SensorInfo]:
    dev_root = dev_root or DEV_ROOT
    sys_root = sys_root or V4L_SYS_ROOT
    zed_paths = zed_paths if zed_paths is not None else ZED_PATHS
    entries: list[SensorInfo] = []

    cameras = list_cameras(dev_root, sys_root)
    entries.append(
        SensorInfo(
            "cameras",
            "video4linux",
            bool(cameras),
            f"{len(cameras)} device(s)",
            [f"{device} ({name})" if name else device for device, name in cameras],
            "check the device with 'v4l2-ctl --list-devices'",
        )
    )

    realsense = pydist.pip_version("pyrealsense2")
    entries.append(
        SensorInfo(
            "realsense",
            "depth-camera",
            bool(realsense),
            f"pyrealsense2 {realsense}" if realsense else "pyrealsense2 not installed",
            hint="pip install pyrealsense2",
        )
    )

    zed = next((str(path) for path in zed_paths if path.is_dir()), None)
    entries.append(
        SensorInfo(
            "zed",
            "depth-camera",
            bool(zed),
            zed or "ZED SDK not found",
            hint="install the ZED SDK from stereolabs.com",
        )
    )

    serials = list_serial_devices(dev_root)
    entries.append(
        SensorInfo(
            "lidar",
            "serial",
            bool(serials),
            f"{len(serials)} serial device(s)",
            serials,
            "connect the LiDAR and check udev rules",
        )
    )

    status, detail, _hint = detect_isaac_sim(config)
    entries.append(
        SensorInfo(
            "isaacsim",
            "simulation",
            status == "ok",
            detail,
            hint="register Isaac Sim: caasi setup isaacsim",
        )
    )
    return entries
